from decimal import Decimal
from datetime import datetime
from math import exp
from models import SensorData, ProcessedData, Alert, AlertType, Severity, AlertStatus
from sqlalchemy.orm import Session

LOW_BATTERY_THRESHOLD = 20
ANOMALY_FLOW_DROP = 0.5

# ---------------- SIGMOID FUNCTION ---------------- #
def sigmoid(x, x0=0, k=1):
    """Standard sigmoid: smooth mapping to 0-1"""
    return 1 / (1 + exp(-k*(x-x0)))

def compute_leak_probability_sigmoid(flow1, flow2, battery1, battery2):
    """
    Returns leak probability 0-100% based on two-sensor readings using sigmoid logic
    """
    # Average flow and flow difference
    flow_avg = (flow1 + flow2) / 2
    flow_diff = abs(flow1 - flow2)
    battery_avg = (battery1 + battery2) / 2

    # Sigmoid mappings (tunable)
    flow_score = sigmoid(flow_avg, x0=50, k=0.1)       # higher flow → higher leak
    diff_score = sigmoid(flow_diff, x0=5, k=0.5)       # higher difference → higher leak
    battery_score = 1 - sigmoid(battery_avg, x0=30, k=0.2)  # low battery → increase leak prob

    # Weighted combination (can tune weights)
    leak_prob = (0.5*flow_score + 0.4*diff_score + 0.1*battery_score) * 100
    return leak_prob

# ---------------- PROCESS SENSOR DATA ---------------- #
def process_sensor_data_pairwise(db: Session, sensors: list, new_readings: dict):
    """
    sensors: list of Sensor objects along the pipeline in order
    new_readings: dict {sensor_id: SensorData object just received}
    """
    alerts = []
    
    # Compute processed data for each sensor individually
    for sensor in sensors:
        sensor_data = new_readings[sensor.sensor_id]
        # Smoothed flow: average of last 5 readings
        last_proc = db.query(ProcessedData).filter(ProcessedData.sensor_id==sensor.sensor_id).order_by(ProcessedData.timestamp.desc()).limit(5).all()
        if last_proc:
            smoothed_flow = float(sum([p.smoothed_flow for p in last_proc])/len(last_proc))
        else:
            smoothed_flow = float(sensor_data.flow_rate)

        flow_diff = 0
        if last_proc:
            flow_diff = float(smoothed_flow - last_proc[0].smoothed_flow)

        processed = ProcessedData(
            sensor_id=sensor.sensor_id,
            timestamp=sensor_data.timestamp,
            smoothed_flow=Decimal(smoothed_flow),
            flow_diff=Decimal(flow_diff)
        )
        db.add(processed)
    db.commit()

    # ---------------- CHECK PAIRS ---------------- #
    for i in range(len(sensors)-1):
        s1 = sensors[i]
        s2 = sensors[i+1]
        d1 = new_readings[s1.sensor_id]
        d2 = new_readings[s2.sensor_id]

        # Compute leak probability using sigmoid fuzzy logic
        leak_prob = compute_leak_probability_sigmoid(d1.flow_rate, d2.flow_rate, d1.battery_level, d2.battery_level)

        # Determine severity
        if leak_prob < 50:
            severity = Severity.low
        elif leak_prob < 70:
            severity = Severity.medium
        else:
            severity = Severity.high

        # Create leak alert if probability > 50%
        if leak_prob >= 50:
            alert = Alert(
                sensor_from = s1.sensor_id,
                sensor_to = s2.sensor_id,
                timestamp = datetime.utcnow(),
                alert_type = AlertType.leak,
                severity = severity,
                probability = leak_prob,
                status = AlertStatus.active
            )
            db.add(alert)
            alerts.append(alert)

        # Optional: anomaly based on sudden negative drop in either sensor
        if (d1.flow_rate - d2.flow_rate) < -ANOMALY_FLOW_DROP:
            alert = Alert(
                sensor_from = s1.sensor_id,
                sensor_to = s2.sensor_id,
                timestamp = datetime.utcnow(),
                alert_type = AlertType.anomaly,
                severity = Severity.medium,
                probability = 85.0,
                status = AlertStatus.active
            )
            db.add(alert)
            alerts.append(alert)

        # Low battery alerts
        for s, d in [(s1,d1),(s2,d2)]:
            if d.battery_level < LOW_BATTERY_THRESHOLD:
                alert = Alert(
                    sensor_from = s.sensor_id,
                    sensor_to = s.sensor_id,
                    timestamp = datetime.utcnow(),
                    alert_type = AlertType.low_battery,
                    severity = Severity.low,
                    probability = 90.0,
                    status = AlertStatus.active
                )
                db.add(alert)
                alerts.append(alert)

    if alerts:
        db.commit()
        for a in alerts:
            db.refresh(a)

    return alerts
