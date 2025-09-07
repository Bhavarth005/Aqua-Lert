from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from .. import crud, schemas
from ..database import get_db

router = APIRouter()

@router.post("/data")
def receive_sensor_data(payload: schemas.SensorDataCreate, db: Session = Depends(get_db)):
    # Store raw data
    record = crud.create_sensor_data(db, payload)

    # TODO: call preprocessing + fuzzy logic here later
    return {"message": "Data received", "id": record.id}
