from collections import defaultdict
from decimal import Decimal
from datetime import datetime
from math import exp
from app.models import (
    SensorData,
    ProcessedData,
    Alert,
    AlertType,
    Severity,
    AlertStatus,
    PipelineTopology
)
from sqlalchemy.orm import Session

LOW_BATTERY_THRESHOLD = 20
ANOMALY_FLOW_DROP = 0.5

# ---------------- SIGMOID FUNCTION ---------------- #
def sigmoid(x, x0=0, k=1):
    """Standard sigmoid: smooth mapping to 0-1"""
    return 1 / (1 + exp(-k * (x - x0)))


def compute_leak_probability_sigmoid(flow1, flow2, battery1, battery2):
    """
    Returns leak probability 0-100% based on two-sensor readings using sigmoid logic
    """
    # Average flow and flow difference
    flow_avg = (flow1 + flow2) / 2
    flow_diff = abs(flow1 - flow2)
    battery_avg = (battery1 + battery2) / 2

    # Sigmoid mappings (tunable)
    flow_score = sigmoid(flow_avg, x0=50, k=0.1)             # higher flow → higher leak
    diff_score = sigmoid(flow_diff, x0=5, k=0.5)             # higher difference → higher leak
    battery_score = 1 - sigmoid(battery_avg, x0=30, k=0.2)   # low battery → increase leak prob

    # Weighted combination (can tune weights)
    leak_prob = (0.5 * flow_score + 0.4 * diff_score + 0.1 * battery_score) * 100
    return leak_prob


# ---------------- HELPER: GET LATEST SENSOR DATA ---------------- #
def get_latest_data(sensor_id: str, new_readings: dict, db: Session):
    """
    Returns the latest SensorData for a given sensor_id.
    Checks new_readings first, otherwise fetches from DB.
    """
    if sensor_id in new_readings:
        return new_readings[sensor_id]
    return (
        db.query(SensorData)
        .filter(SensorData.sensor_id == sensor_id)
        .order_by(SensorData.timestamp.desc())
        .first()
    )


# ---------------- PROCESS SENSOR DATA ---------------- #
def process_sensor_data_topology(db: Session, sensors: list, new_readings: dict, topology: dict):
    """
    sensors: list of Sensor objects in DB
    new_readings: dict {sensor_id: SensorData object just received}
    topology: dict {parent_sensor_id: [child_sensor_ids]}
    """
    alerts = []

    # Compute processed data for each sensor individually
    for sensor in sensors:
        sensor_data = get_latest_data(sensor.sensor_id, new_readings, db)
        if not sensor_data:
            continue

        # Smoothed flow: average of last 5 readings
        last_proc = (
            db.query(ProcessedData)
            .filter(ProcessedData.sensor_id == sensor.sensor_id)
            .order_by(ProcessedData.timestamp.desc())
            .limit(5)
            .all()
        )
        if last_proc:
            smoothed_flow = float(sum([p.smoothed_flow for p in last_proc]) / len(last_proc))
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

    # ---------------- CHECK USING TOPOLOGY ---------------- #
    def traverse_and_check(parent_id):
        parent_data = get_latest_data(parent_id, new_readings, db)
        if not parent_data:
            return

        children = topology.get(parent_id, [])
        for child_id in children:
            child_data = get_latest_data(child_id, new_readings, db)
            if not child_data:
                continue

            # Compute leak probability using sigmoid fuzzy logic
            leak_prob = compute_leak_probability_sigmoid(
                parent_data.flow_rate,
                child_data.flow_rate,
                parent_data.battery_level,
                child_data.battery_level,
            )

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
                    sensor_from=parent_id,
                    sensor_to=child_id,
                    timestamp=datetime.utcnow(),
                    alert_type=AlertType.leak,
                    severity=severity,
                    probability=leak_prob,
                    status=AlertStatus.active,
                )
                db.add(alert)
                alerts.append(alert)

            # Optional: anomaly based on sudden negative drop
            if (parent_data.flow_rate - child_data.flow_rate) < -ANOMALY_FLOW_DROP:
                alert = Alert(
                    sensor_from=parent_id,
                    sensor_to=child_id,
                    timestamp=datetime.utcnow(),
                    alert_type=AlertType.anomaly,
                    severity=Severity.medium,
                    probability=85.0,
                    status=AlertStatus.active,
                )
                db.add(alert)
                alerts.append(alert)

            # Low battery alerts
            for sid, d in [(parent_id, parent_data), (child_id, child_data)]:
                if d.battery_level < LOW_BATTERY_THRESHOLD:
                    alert = Alert(
                        sensor_from=sid,
                        sensor_to=sid,
                        timestamp=datetime.utcnow(),
                        alert_type=AlertType.low_battery,
                        severity=Severity.low,
                        probability=90.0,
                        status=AlertStatus.active,
                    )
                    db.add(alert)
                    alerts.append(alert)

            # Recurse further down the pipeline
            traverse_and_check(child_id)

    # Start traversal from root sensors (those not children of anyone)
    all_children = {c for childs in topology.values() for c in childs}
    roots = [s.sensor_id for s in sensors if s.sensor_id not in all_children]

    for root in roots:
        traverse_and_check(root)

    if alerts:
        db.commit()
        for a in alerts:
            db.refresh(a)

    return alerts


# ---------------- TOPOLOGY BUILDER ---------------- #
def build_topology(db: Session):
    topology = defaultdict(list)
    mappings = db.query(PipelineTopology).all()
    for m in mappings:
        topology[m.parent_sensor_id].append(m.child_sensor_id)
    return topology
