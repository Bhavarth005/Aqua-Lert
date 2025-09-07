from sqlalchemy import Column, String, Integer, Date, Enum, DECIMAL, DateTime, BigInteger, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
import enum

Base = declarative_base()

class SensorStatus(enum.Enum):
    active = "active"
    inactive = "inactive"
    maintenance = "maintenance"

class AlertType(enum.Enum):
    leak = "leak"
    anomaly = "anomaly"
    low_battery = "low_battery"

class Severity(enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"

class AlertStatus(enum.Enum):
    active = "active"
    resolved = "resolved"


class Sensor(Base):
    __tablename__ = "sensors"

    sensor_id = Column(String(50), primary_key=True)
    location = Column(String(100))
    pipe_diameter_mm = Column(Integer)
    install_date = Column(Date)
    status = Column(Enum(SensorStatus), default=SensorStatus.active)


class SensorData(Base):
    __tablename__ = "sensor_data"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    sensor_id = Column(String(50))
    timestamp = Column(DateTime)
    flow_rate = Column(DECIMAL(10, 3))
    battery_level = Column(Integer)


class ProcessedData(Base):
    __tablename__ = "processed_data"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    sensor_id = Column(String(50))
    timestamp = Column(DateTime)
    smoothed_flow = Column(DECIMAL(10, 3))
    flow_diff = Column(DECIMAL(10, 3))


class Alert(Base):
    __tablename__ = "alerts"

    alert_id = Column(BigInteger, primary_key=True, autoincrement=True)
    sensor_from = Column(String(50))  # new: start sensor
    sensor_to = Column(String(50))    # new: end sensor
    timestamp = Column(DateTime)
    alert_type = Column(Enum(AlertType))
    severity = Column(Enum(Severity))
    probability = Column(DECIMAL(5, 2))
    status = Column(Enum(AlertStatus), default=AlertStatus.active)

class PipelineTopology(Base):
    __tablename__ = "pipeline_topology"
    id = Column(Integer, primary_key=True, index=True)
    parent_sensor_id = Column(String(50), ForeignKey("sensors.sensor_id"))
    child_sensor_id = Column(String(50), ForeignKey("sensors.sensor_id"))