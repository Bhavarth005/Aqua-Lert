from sqlalchemy.orm import Session
from app import models, schemas

# --- SENSORS ---
def create_sensor(db: Session, sensor: schemas.SensorCreate):
    new_sensor = models.Sensor(**sensor.dict())
    db.add(new_sensor)
    db.commit()
    db.refresh(new_sensor)
    return new_sensor

def get_sensors(db: Session):
    return db.query(models.Sensor).all()


# --- SENSOR DATA ---
def create_sensor_data(db: Session, data: schemas.SensorDataCreate):
    new_data = models.SensorData(
        sensor_id=data.sensor_id,
        timestamp=data.timestamp,
        flow_rate=data.flow_rate,
        battery_level=data.battery_level
    )
    db.add(new_data)
    db.commit()
    db.refresh(new_data)
    return new_data

def get_sensor_history(db: Session, sensor_id: str, limit: int = 50):
    return (
        db.query(models.SensorData)
        .filter(models.SensorData.sensor_id == sensor_id)
        .order_by(models.SensorData.timestamp.desc())
        .limit(limit)
        .all()
    )


# --- ALERTS ---
def create_alert(db: Session, alert: schemas.AlertCreate):
    new_alert = models.Alert(**alert.dict())
    db.add(new_alert)
    db.commit()
    db.refresh(new_alert)
    return new_alert

def get_active_alerts(db: Session):
    return db.query(models.Alert).filter(models.Alert.status == "active").all()
