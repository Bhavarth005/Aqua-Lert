from decimal import Decimal
from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.database import SessionLocal, engine
from app.models import Base, Sensor, SensorStatus, SensorData, Alert, AlertType, Severity, AlertStatus, PipelineTopology
from datetime import datetime
from typing import List, Dict
from app.utils import process_sensor_data_topology, build_topology

# Create tables
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Smart Water Leakage API")
app.add_middleware(CORSMiddleware, allow_origins="*", allow_credentials=True, allow_methods=["*"], allow_headers=["*"], )

# ------------------- DB Session ------------------- #
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ------------------- Pydantic Models ------------------- #
class SensorReading(BaseModel):
    sensor_id: str
    flow_rate: float
    battery_level: int
    timestamp: datetime        

class TopologyMapping(BaseModel):
    parent_sensor_id: str
    child_sensor_id: str

# ------------------- SENSOR ROUTES ------------------- #
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

@app.get("/sensors")
def list_sensors(db: Session = Depends(get_db)):
    return db.query(Sensor).all()

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

    db.query(SensorData).filter(SensorData.sensor_id == sensor_id).delete()
    db.query(Alert).filter(Alert.sensor_from == sensor_id).delete()
    db.query(Alert).filter(Alert.sensor_to == sensor_id).delete()
    db.query(PipelineTopology).filter(
        (PipelineTopology.parent_sensor_id == sensor_id) | 
        (PipelineTopology.child_sensor_id == sensor_id)
    ).delete()

    db.delete(sensor)
    db.commit()
    return {"message": f"Sensor {sensor_id} and its data/alerts deleted successfully"}

# ------------------- TOPOLOGY ROUTES ------------------- #
@app.post("/topology/add")
def add_topology(mapping: TopologyMapping, db: Session = Depends(get_db)):
    parent = db.query(Sensor).filter(Sensor.sensor_id == mapping.parent_sensor_id).first()
    child = db.query(Sensor).filter(Sensor.sensor_id == mapping.child_sensor_id).first()

    if not parent or not child:
        raise HTTPException(status_code=404, detail="Parent or child sensor not found")

    db.add(PipelineTopology(
        parent_sensor_id=mapping.parent_sensor_id,
        child_sensor_id=mapping.child_sensor_id
    ))
    db.commit()
    return {"message": "Topology mapping added successfully"}

@app.get("/topology/view")
def view_topology(db: Session = Depends(get_db)):
    topology = build_topology(db)
    return dict(topology)

# ------------------- SENSOR DATA ROUTES ------------------- #
@app.post("/sensors/{sensor_id}/data")
def add_sensor_data(sensor_id: str, flow_rate: float, battery_level: int, db: Session = Depends(get_db)):
    sensor = db.query(Sensor).filter(Sensor.sensor_id == sensor_id).first()
    if not sensor:
        raise HTTPException(status_code=404, detail="Sensor not found")

    new_data = SensorData(
        sensor_id=sensor_id,
        flow_rate=flow_rate,
        battery_level=battery_level,
        timestamp=datetime.utcnow()
    )
    db.add(new_data)
    db.commit()
    db.refresh(new_data)

    topology = build_topology(db)
    sensors = [sensor]  # Only process the current sensor
    sensor_data_dict = {sensor_id: new_data}

    alerts = process_sensor_data_topology(db, sensors, sensor_data_dict, topology)

    return {
        "message": "Data added successfully",
        "data_id": new_data.id,
        "alerts": [
            {
                "alert_id": a.alert_id,
                "sensor_from": a.sensor_from,
                "sensor_to": a.sensor_to,
                "alert_type": a.alert_type.value,
                "severity": a.severity.value,
                "probability": float(a.probability),
                "timestamp": a.timestamp.isoformat(),
                "status": a.status.value
            } for a in alerts
        ]
    }

@app.post("/sensors/data")
def receive_sensor_data(readings: List[SensorReading], db: Session = Depends(get_db)):
    sensors = db.query(Sensor).all()
    if not sensors:
        raise HTTPException(status_code=404, detail="No sensors found in database")

    sensor_data_dict = {
        r.sensor_id: SensorData(
            sensor_id=r.sensor_id,
            flow_rate=r.flow_rate,
            battery_level=r.battery_level,
            timestamp=r.timestamp
        ) for r in readings
    }

    topology = build_topology(db)
    alerts = process_sensor_data_topology(db, sensors, sensor_data_dict, topology)

    return {
        "alerts_generated": [
            {
                "alert_id": a.alert_id,
                "sensor_from": a.sensor_from,
                "sensor_to": a.sensor_to,
                "alert_type": a.alert_type.value,
                "severity": a.severity.value,
                "probability": float(a.probability),
                "timestamp": a.timestamp.isoformat(),
                "status": a.status.value
            } for a in alerts
        ]
    }

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

# ---------------- ADDITIONAL ROUTES ---------------- #

# Filter Sensor Data by Date / Limit

@app.get("/sensors/{sensor_id}/data/filter")
def get_filtered_sensor_data(
    sensor_id: str,
    start: str = Query(None, description="Start datetime ISO format"),
    end: str = Query(None, description="End datetime ISO format"),
    limit: int = Query(50, description="Max number of records"),
    db: Session = Depends(get_db)
):
    sensor = db.query(Sensor).filter(Sensor.sensor_id == sensor_id).first()
    if not sensor:
        raise HTTPException(status_code=404, detail="Sensor not found")

    query = db.query(SensorData).filter(SensorData.sensor_id == sensor_id)

    if start:
        start_dt = datetime.fromisoformat(start)
        query = query.filter(SensorData.timestamp >= start_dt)
    if end:
        end_dt = datetime.fromisoformat(end)
        query = query.filter(SensorData.timestamp <= end_dt)

    readings = query.order_by(SensorData.timestamp.desc()).limit(limit).all()
    return readings

# Filter Alerts by Sensor / Type / Severity

@app.get("/alerts/filter")
def get_filtered_alerts(
    sensor_id: str = None,
    alert_type: AlertType = None,
    severity: Severity = None,
    status: AlertStatus = AlertStatus.active,
    db: Session = Depends(get_db)
):
    query = db.query(Alert)

    if sensor_id:
        query = query.filter(Alert.sensor_id == sensor_id)
    if alert_type:
        query = query.filter(Alert.alert_type == alert_type)
    if severity:
        query = query.filter(Alert.severity == severity)
    if status:
        query = query.filter(Alert.status == status)

    alerts = query.order_by(Alert.timestamp.desc()).all()
    return alerts

# Bulk Resolve Alerts

@app.post("/alerts/resolve/bulk")
def bulk_resolve_alerts(alert_ids: List[int], db: Session = Depends(get_db)):
    alerts = db.query(Alert).filter(Alert.alert_id.in_(alert_ids)).all()
    if not alerts:
        raise HTTPException(status_code=404, detail="No alerts found")

    for alert in alerts:
        alert.status = AlertStatus.resolved

    db.commit()
    return {"message": f"{len(alerts)} alerts resolved successfully"}
