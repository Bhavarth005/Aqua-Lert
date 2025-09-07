from decimal import Decimal
from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import SessionLocal, engine
from app.models import Base, Sensor, SensorStatus, SensorData, Alert, AlertType, Severity, AlertStatus
from datetime import datetime

# Create tables (already done, but safe to keep)
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Smart Water Leakage API")

# Dependency to get DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ---------------- SENSOR ROUTES ---------------- #

# Register a new sensor
@app.post("/sensors")
def create_sensor(sensor_id: str, location: str, pipe_diameter_mm: int, db: Session = Depends(get_db)):
    existing = db.query(Sensor).filter(Sensor.sensor_id == sensor_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Sensor already exists")
    
    new_sensor = Sensor(
        sensor_id=sensor_id,
        location=location,
        pipe_diameter_mm=pipe_diameter_mm
    )
    db.add(new_sensor)
    db.commit()
    db.refresh(new_sensor)
    return {"message": "Sensor registered successfully", "sensor": sensor_id}

# List all sensors
@app.get("/sensors")
def list_sensors(db: Session = Depends(get_db)):
    sensors = db.query(Sensor).all()
    return sensors

@app.put("/sensors/{sensor_id}")
def update_sensor(
    sensor_id: str,
    location: str = None,
    pipe_diameter_mm: int = None,
    status: SensorStatus = None,
    db: Session = Depends(get_db)
):
    sensor = db.query(Sensor).filter(Sensor.sensor_id == sensor_id).first()
    if not sensor:
        raise HTTPException(status_code=404, detail="Sensor not found")

    # Update only provided fields
    if location is not None:
        sensor.location = location
    if pipe_diameter_mm is not None:
        sensor.pipe_diameter_mm = pipe_diameter_mm
    if status is not None:
        sensor.status = status

    db.commit()
    db.refresh(sensor)
    return {"message": "Sensor updated successfully", "sensor": sensor_id}

@app.delete("/sensors/{sensor_id}")
def delete_sensor(sensor_id: str, db: Session = Depends(get_db)):
    sensor = db.query(Sensor).filter(Sensor.sensor_id == sensor_id).first()
    if not sensor:
        raise HTTPException(status_code=404, detail="Sensor not found")

    # Delete related sensor data
    db.query(SensorData).filter(SensorData.sensor_id == sensor_id).delete()
    # Delete related alerts
    db.query(Alert).filter(Alert.sensor_id == sensor_id).delete()
    # Delete sensor
    db.delete(sensor)
    db.commit()

    return {"message": f"Sensor {sensor_id} and its data/alerts deleted successfully"}


# ---------------- SENSOR DATA ROUTES ---------------- #

# Add a new reading for a sensor
@app.post("/sensors/{sensor_id}/data")
def add_sensor_data(sensor_id: str, flow_rate: float, battery_level: int, db: Session = Depends(get_db)):
    sensor = db.query(Sensor).filter(Sensor.sensor_id == sensor_id).first()
    if not sensor:
        raise HTTPException(status_code=404, detail="Sensor not found")

    new_data = SensorData(
    sensor_id=sensor_id,
    timestamp=datetime.utcnow(),
    flow_rate=flow_rate,
    battery_level=battery_level
    )
    db.add(new_data)
    db.commit()
    db.refresh(new_data)

    # Run alert checks
    alerts = check_for_alerts(db, new_data)
    return {"message": "Data added successfully", "data_id": new_data.id, "alerts": [a.alert_type.value for a in alerts]}


# Fetch recent readings for a sensor
@app.get("/sensors/{sensor_id}/data")
def get_sensor_data(sensor_id: str, limit: int = 10, db: Session = Depends(get_db)):
    sensor = db.query(Sensor).filter(Sensor.sensor_id == sensor_id).first()
    if not sensor:
        raise HTTPException(status_code=404, detail="Sensor not found")

    readings = db.query(SensorData).filter(SensorData.sensor_id == sensor_id).order_by(SensorData.timestamp.desc()).limit(limit).all()
    return readings

@app.put("/sensors/{sensor_id}/data/{data_id}")
def update_sensor_data(
    sensor_id: str,
    data_id: int,
    flow_rate: float = None,
    battery_level: int = None,
    db: Session = Depends(get_db)
):
    data = db.query(SensorData).filter(SensorData.id == data_id, SensorData.sensor_id == sensor_id).first()
    if not data:
        raise HTTPException(status_code=404, detail="Sensor data not found")

    if flow_rate is not None:
        data.flow_rate = flow_rate
    if battery_level is not None:
        data.battery_level = battery_level

    db.commit()
    db.refresh(data)
    return {"message": "Sensor data updated successfully", "data_id": data_id}

@app.delete("/sensors/{sensor_id}/data/{data_id}")
def delete_sensor_data(sensor_id: str, data_id: int, db: Session = Depends(get_db)):
    data = db.query(SensorData).filter(SensorData.id == data_id, SensorData.sensor_id == sensor_id).first()
    if not data:
        raise HTTPException(status_code=404, detail="Sensor data not found")

    db.delete(data)
    db.commit()
    return {"message": f"Sensor data {data_id} deleted successfully"}

# ---------------- ALERT ROUTES ---------------- #

LEAK_FLOW_THRESHOLD = Decimal("15.0")
LOW_BATTERY_THRESHOLD = 20

def check_for_alerts(db: Session, sensor_data: SensorData):
    alerts_created = []

    # Leak detection
    if sensor_data.flow_rate > LEAK_FLOW_THRESHOLD:
        alert = Alert(
            sensor_id=sensor_data.sensor_id,
            timestamp=sensor_data.timestamp,
            alert_type=AlertType.leak,
            severity=Severity.high,
            probability=95.0,  # example
            status=AlertStatus.active
        )
        db.add(alert)
        alerts_created.append(alert)

    # Low battery
    if sensor_data.battery_level < LOW_BATTERY_THRESHOLD:
        alert = Alert(
            sensor_id=sensor_data.sensor_id,
            timestamp=sensor_data.timestamp,
            alert_type=AlertType.low_battery,
            severity=Severity.medium,
            probability=90.0,
            status=AlertStatus.active
        )
        db.add(alert)
        alerts_created.append(alert)

    if alerts_created:
        db.commit()
        for a in alerts_created:
            db.refresh(a)
    return alerts_created

@app.get("/alerts")
def get_active_alerts(db: Session = Depends(get_db)):
    alerts = db.query(Alert).filter(Alert.status == AlertStatus.active).order_by(Alert.timestamp.desc()).all()
    return alerts

@app.post("/alerts/resolve/{alert_id}")
def resolve_alert(alert_id: int, db: Session = Depends(get_db)):
    alert = db.query(Alert).filter(Alert.alert_id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    if alert.status == AlertStatus.resolved:
        return {"message": "Alert already resolved", "alert_id": alert_id}

    alert.status = AlertStatus.resolved
    db.commit()
    db.refresh(alert)
    return {"message": "Alert resolved successfully", "alert_id": alert_id}

@app.put("/alerts/{alert_id}")
def update_alert(
    alert_id: int,
    severity: Severity = None,
    status: AlertStatus = None,
    db: Session = Depends(get_db)
):
    alert = db.query(Alert).filter(Alert.alert_id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    if severity is not None:
        alert.severity = severity
    if status is not None:
        alert.status = status

    db.commit()
    db.refresh(alert)
    return {"message": "Alert updated successfully", "alert_id": alert_id}

@app.delete("/alerts/{alert_id}")
def delete_alert(alert_id: int, db: Session = Depends(get_db)):
    alert = db.query(Alert).filter(Alert.alert_id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    db.delete(alert)
    db.commit()
    return {"message": f"Alert {alert_id} deleted successfully"}

