from decimal import Decimal
from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.database import SessionLocal, engine
from app.models import (
    Base,
    Sensor,
    SensorStatus,
    SensorData,
    Alert,
    AlertType,
    Severity,
    AlertStatus,
)
from datetime import datetime, date
from typing import List
from app.utils import process_sensor_data_topology

# Create tables
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Smart Water Leakage API")
app.add_middleware(
    CORSMiddleware,
    allow_origins="*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
    battery_level: int = None
    timestamp: datetime = None


@app.get("/")
def default():
    return {"message": "Aqua-Lert Backend is up and running"}

# ------------------- SENSOR ROUTES ------------------- #
@app.post("/sensors")
def create_sensor(
    sensor_id: str,
    location: str,
    pipe_diameter_mm: int,
    parent_sensor_id: str = None,
    db: Session = Depends(get_db),
):
    existing = db.query(Sensor).filter(Sensor.sensor_id == sensor_id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Sensor already exists")

    new_sensor = Sensor(
        sensor_id=sensor_id,
        location=location,
        pipe_diameter_mm=pipe_diameter_mm,
        parent_sensor_id=parent_sensor_id,
    )
    db.add(new_sensor)
    db.commit()
    db.refresh(new_sensor)
    return {"message": "Sensor registered successfully", "sensor": new_sensor}


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
    parent_sensor_id: str = None,
    db: Session = Depends(get_db),
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
    if parent_sensor_id is not None:
        sensor.parent_sensor_id = parent_sensor_id

    db.commit()
    db.refresh(sensor)
    return {"message": "Sensor updated successfully", "sensor": sensor}


@app.delete("/sensors/{sensor_id}")
def delete_sensor(sensor_id: str, db: Session = Depends(get_db)):
    sensor = db.query(Sensor).filter(Sensor.sensor_id == sensor_id).first()
    if not sensor:
        raise HTTPException(status_code=404, detail="Sensor not found")

    db.query(SensorData).filter(SensorData.sensor_id == sensor_id).delete()
    db.query(Alert).filter(Alert.sensor_from == sensor_id).delete()
    db.query(Alert).filter(Alert.sensor_to == sensor_id).delete()

    db.delete(sensor)
    db.commit()
    return {"message": f"Sensor {sensor_id} and its data/alerts deleted successfully"}


# ------------------- SENSOR DATA ROUTES ------------------- #
@app.get("/sensors/{sensor_id}/data")
def get_sensor_data(sensor_id: str, limit: int = 10, db: Session = Depends(get_db)):
    if sensor_id == "all":
        # Get latest records for all sensors, limited by 'limit' timestamps
        readings = (
            db.query(SensorData)
            .order_by(SensorData.timestamp.desc())
            .limit(limit * db.query(SensorData.sensor_id).distinct().count())
            .all()
        )

        # Group by timestamp
        grouped = {}
        for r in readings:
            ts = r.timestamp.isoformat()
            if ts not in grouped:
                grouped[ts] = {"time": ts}
            grouped[ts][r.sensor_id] = float(r.flow_rate)

        # Sort by timestamp desc and limit
        return sorted(grouped.values(), key=lambda x: x["time"], reverse=True)[:limit]

    else:
        sensor = db.query(Sensor).filter(Sensor.sensor_id == sensor_id).first()
        if not sensor:
            raise HTTPException(status_code=404, detail="Sensor not found")

        readings = (
            db.query(SensorData)
            .filter(SensorData.sensor_id == sensor_id)
            .order_by(SensorData.timestamp.desc())
            .limit(limit)
            .all()
        )

        # Convert to desired format
        return [
            {"time": r.timestamp.isoformat(), sensor_id: float(r.flow_rate)}
            for r in readings
        ]



@app.post("/sensors/data")
def receive_sensor_data(readings: List[SensorReading], db: Session = Depends(get_db)):
    sensors = db.query(Sensor).all()
    if not sensors:
        raise HTTPException(status_code=404, detail="No sensors found in database")
    time_now = datetime.utcnow()
    sensor_data_dict = {}
    for r in readings:
        new_data = SensorData(
            sensor_id=r.sensor_id,
            flow_rate=r.flow_rate,
            battery_level=r.battery_level if r.battery_level else 100,
            timestamp=r.timestamp if r.timestamp else time_now,
        )
        db.add(new_data)  
        db.commit()
        db.refresh(new_data)

        sensor_data_dict[r.sensor_id] = new_data

    alerts = process_sensor_data_topology(db, sensors, sensor_data_dict, {})
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
                "status": a.status.value,
            }
            for a in alerts
        ]
    }


@app.get("/sensors/{sensor_id}/data")
def get_sensor_data(sensor_id: str, limit: int = 10, db: Session = Depends(get_db)):
    if sensor_id == "all":
        readings = (
            db.query(SensorData)
            .order_by(SensorData.timestamp.desc())
            .limit(limit)
            .all()
        )
        return readings

    sensor = db.query(Sensor).filter(Sensor.sensor_id == sensor_id).first()
    if not sensor:
        raise HTTPException(status_code=404, detail="Sensor not found")

    readings = (
        db.query(SensorData)
        .filter(SensorData.sensor_id == sensor_id)
        .order_by(SensorData.timestamp.desc())
        .limit(limit)
        .all()
    )
    return readings


# ---------------- ALERT ROUTES ---------------- #
@app.get("/alerts")
def get_alerts(
    status: AlertStatus = None,   # optional filter
    db: Session = Depends(get_db)
):
    query = db.query(Alert)
    
    # if status query param is passed (active / resolved), filter it
    if status:
        query = query.filter(Alert.status == status)
    
    alerts = query.order_by(Alert.timestamp.desc()).all()

    return [
        {
            "alert_id": a.alert_id,
            "sensor_from": a.sensor_from,
            "sensor_to": a.sensor_to,
            "alert_type": a.alert_type.value,
            "severity": a.severity.value,
            "probability": float(a.probability),
            "timestamp": a.timestamp.isoformat(),
            "status": a.status.value,
        }
        for a in alerts
    ]


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


# ---------------- ANALYTICS ROUTES ---------------- #
@app.get("/analytics/usage/weekly")
def get_weekly_usage(db: Session = Depends(get_db)):
    results = (
        db.query(
            func.date(SensorData.timestamp).label("day"),
            func.sum(SensorData.flow_rate).label("total_flow"),
        )
        .group_by(func.date(SensorData.timestamp))
        .order_by(func.date(SensorData.timestamp).desc())
        .limit(7)
        .all()
    )
    return [{"day": r.day.strftime("%A"), "total_flow": float(r.total_flow)} for r in results]


@app.get("/analytics/usage/today")
def get_today_usage(db: Session = Depends(get_db)):
    today = date.today()
    total = (
        db.query(func.sum(SensorData.flow_rate))
        .filter(func.date(SensorData.timestamp) == today)
        .scalar()
    )
    return {"day": str(today), "total_flow": float(total or 0)}


@app.get("/analytics/alerts/resolved/today")
def get_resolved_alerts_today(db: Session = Depends(get_db)):
    today = date.today()
    count = (
        db.query(func.count(Alert.alert_id))
        .filter(Alert.status == AlertStatus.resolved)
        .filter(func.date(Alert.timestamp) == today)
        .scalar()
    )
    return {"day": str(today), "resolved_alerts": count}
