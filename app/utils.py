from app.models import SensorData, ProcessedData, Alert, AlertType, Severity, AlertStatus
from sqlalchemy.orm import Session
from decimal import Decimal
from datetime import datetime

WINDOW_SIZE = 5  # Number of recent readings for smoothing
THRESHOLD_MULTIPLIER = 3  # For dynamic anomaly detection

# ----------------- PROCESSING FUNCTIONS ----------------- #

def compute_smoothed_flow(db: Session, sensor_id: str) -> Decimal:
    """Compute moving average of last N sensor readings."""
    last_readings = (
        db.query(SensorData)
        .filter(SensorData.sensor_id == sensor_id)
        .order_by(SensorData.timestamp.desc())
        .limit(WINDOW_SIZE)
        .all()
    )
    if not last_readings:
        return Decimal(0)

    avg_flow = sum([r.flow_rate for r in last_readings]) / len(last_readings)
    return Decimal(avg_flow)


def compute_flow_diff(db: Session, sensor_id: str, current_flow: Decimal) -> Decimal:
    """Compute difference between current smoothed flow and last processed flow."""
    last_processed = (
        db.query(ProcessedData)
        .filter(ProcessedData.sensor_id == sensor_id)
        .order_by(ProcessedData.timestamp.desc())
        .first()
    )
    if last_processed:
        diff = current_flow - last_processed.smoothed_flow
    else:
        diff = Decimal(0)
    return diff


LOW_BATTERY_THRESHOLD = 20  # percent
ANOMALY_FLOW_DROP = 0.5      # sudden drop in flow (units same as flow_rate)

def process_sensor_data(db: Session, sensor_data: SensorData):
    smoothed_flow = compute_smoothed_flow(db, sensor_data.sensor_id)
    flow_diff = compute_flow_diff(db, sensor_data.sensor_id, smoothed_flow)

    processed = ProcessedData(
        sensor_id=sensor_data.sensor_id,
        timestamp=sensor_data.timestamp,
        smoothed_flow=smoothed_flow,
        flow_diff=flow_diff
    )
    db.add(processed)
    db.commit()
    db.refresh(processed)

    alerts = []

    # ---------- Leak Alert ----------
    historical_flows = db.query(ProcessedData.smoothed_flow).filter(
        ProcessedData.sensor_id == sensor_data.sensor_id
    ).all()

    if historical_flows:
        mean_flow = sum([f[0] for f in historical_flows]) / len(historical_flows)
        std_flow = (sum([(f[0]-mean_flow)**2 for f in historical_flows]) / len(historical_flows))**0.5

        if smoothed_flow > mean_flow + 3*std_flow:
            alert = Alert(
                sensor_id=sensor_data.sensor_id,
                timestamp=sensor_data.timestamp,
                alert_type=AlertType.leak,
                severity=Severity.high,
                probability=95.0,
                status=AlertStatus.active
            )
            db.add(alert)
            alerts.append(alert)

        # ---------- Anomaly Alert ----------
        if flow_diff < -ANOMALY_FLOW_DROP:
            alert = Alert(
                sensor_id=sensor_data.sensor_id,
                timestamp=sensor_data.timestamp,
                alert_type=AlertType.anomaly,
                severity=Severity.medium,
                probability=85.0,
                status=AlertStatus.active
            )
            db.add(alert)
            alerts.append(alert)

    # ---------- Low Battery Alert ----------
    if sensor_data.battery_level < LOW_BATTERY_THRESHOLD:
        alert = Alert(
            sensor_id=sensor_data.sensor_id,
            timestamp=sensor_data.timestamp,
            alert_type=AlertType.low_battery,
            severity=Severity.low,
            probability=90.0,
            status=AlertStatus.active
        )
        db.add(alert)
        alerts.append(alert)

    if alerts:
        db.commit()
        for a in alerts:
            db.refresh(a)

    return processed, alerts

