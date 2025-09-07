from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class SensorBase(BaseModel):
    sensor_id: str
    location: Optional[str]
    pipe_diameter_mm: Optional[int]
    install_date: Optional[datetime]
    status: Optional[str]

class SensorCreate(SensorBase):
    pass

class SensorResponse(SensorBase):
    class Config:
        from_attributes = True


class SensorDataBase(BaseModel):
    sensor_id: str
    timestamp: datetime
    flow_rate: float
    battery_level: int

class SensorDataCreate(SensorDataBase):
    pass

class SensorDataResponse(SensorDataBase):
    id: int
    class Config:
        from_attributes = True


class ProcessedDataBase(BaseModel):
    sensor_id: str
    timestamp: datetime
    smoothed_flow: float
    flow_diff: float

class ProcessedDataCreate(ProcessedDataBase):
    pass

class ProcessedDataResponse(ProcessedDataBase):
    id: int
    class Config:
        from_attributes = True


class AlertBase(BaseModel):
    sensor_id: str
    timestamp: datetime
    alert_type: str
    severity: str
    probability: float
    status: Optional[str] = "active"

class AlertCreate(AlertBase):
    pass

class AlertResponse(AlertBase):
    alert_id: int
    class Config:
        from_attributes = True
