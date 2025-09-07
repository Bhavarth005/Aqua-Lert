import numpy as np
import skfuzzy as fuzz
from skfuzzy import control as ctrl
from decimal import Decimal
from datetime import datetime
from models import SensorData, ProcessedData, Alert, AlertType, Severity, AlertStatus
from sqlalchemy.orm import Session

WINDOW_SIZE = 5
LOW_BATTERY_THRESHOLD = 20
ANOMALY_FLOW_DROP = 0.5

# ----------------- FUZZY LOGIC FUNCTION ----------------- #
def compute_leak_probability(flow, flow_diff, battery):
    # Fuzzy variables
    flow_var = ctrl.Antecedent(np.arange(0, 101, 1), 'flow')
    diff_var = ctrl.Antecedent(np.arange(-50, 51, 1), 'flow_diff')
    battery_var = ctrl.Antecedent(np.arange(0, 101, 1), 'battery')
    leak_prob = ctrl.Consequent(np.arange(0, 101, 1), 'leak_prob')

    # Membership functions
    flow_var['low'] = fuzz.trimf(flow_var.universe, [0, 0, 50])
    flow_var['medium'] = fuzz.trimf(flow_var.universe, [25, 50, 75])
    flow_var['high'] = fuzz.trimf(flow_var.universe, [50, 100, 100])

    diff_var['stable'] = fuzz.trimf(diff_var.universe, [-50, 0, 50])
    diff_var['sudden'] = fuzz.trimf(diff_var.universe, [0, 50, 50])

    battery_var['low'] = fuzz.trimf(battery_var.universe, [0, 0, 30])
    battery_var['good'] = fuzz.trimf(battery_var.universe, [20, 100, 100])

    leak_prob['low'] = fuzz.trimf(leak_prob.universe, [0, 0, 50])
    leak_prob['medium'] = fuzz.trimf(leak_prob.universe, [25, 50, 75])
    leak_prob['high'] = fuzz.trimf(leak_prob.universe, [50, 100, 100])

    # Rules
    rules = [
        ctrl.Rule(flow_var['high'] & diff_var['sudden'], leak_prob['high']),
        ctrl.Rule(flow_var['medium'] & diff_var['sudden'], leak_prob['medium']),
        ctrl.Rule(flow_var['low'] & diff_var['stable'], leak_prob['low']),
        ctrl.Rule(battery_var['low'], leak_prob['medium'])
    ]

    system = ctrl.ControlSystem(rules)
    sim = ctrl.ControlSystemSimulation(system)

    sim.input['flow'] = flow
    sim.input['flow_diff'] = flow_diff
    sim.input['battery'] = battery

    sim.compute()
    return sim.output['leak_prob']  # 0-100%

# ----------------- PROCESSING FUNCTION ----------------- #
def compute_smoothed_flow(db: Session, sensor_id: str) -> Decimal:
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

def process_sensor_data(db: Session, sensor_data: SensorData, sensor):
    # 1. Compute smoothed flow and flow_diff
    smoothed_flow = compute_smoothed_flow(db, sensor_data.sensor_id)
    flow_diff = compute_flow_diff(db, sensor_data.sensor_id, smoothed_flow)

    # 2. Save processed data
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

    # 3. Compute leak probability using fuzzy logic
    leak_prob = compute_leak_probability(float(smoothed_flow), float(flow_diff), sensor_data.battery_level)

    # 4. Classify leak severity based on leak_prob and flow_diff
    leak_severity = None
    if leak_prob < 50:
        leak_severity = Severity.low
    elif leak_prob < 70 or abs(flow_diff) < 1.0:
        leak_severity = Severity.medium
    else:
        leak_severity = Severity.high

    # 5. Create leak alert if probability > 50%
    if leak_prob >= 50:
        alert = Alert(
            sensor_id=sensor_data.sensor_id,
            timestamp=sensor_data.timestamp,
            alert_type=AlertType.leak,
            severity=leak_severity,
            probability=leak_prob,
            status=AlertStatus.active
        )
        db.add(alert)
        alerts.append(alert)

    # 6. Anomaly alert: sudden negative flow spike
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

    # 7. Low battery alert
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
