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
    status = Column(Enum(SensorStatus), default=SensorStatus.active)


class SensorData(Base):
    __tablename__ = "sensor_data"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    sensor_id = Column(String(50))
    timestamp = Column(DateTime)
    flow_rate = Column(DECIMAL(10, 3))


from sqlalchemy import UniqueConstraint, Enum as SQLEnum

class Alert(Base):
    __tablename__ = "alerts"

    alert_id = Column(Integer, primary_key=True, index=True)
    sensor_from = Column(Integer, ForeignKey("sensors.sensor_id"))
    sensor_to = Column(Integer, ForeignKey("sensors.sensor_id"))
    alert_type = Column(SQLEnum(AlertType))
    severity = Column(SQLEnum(Severity))
    probability = Column(DECIMAL(5, 2))
    timestamp = Column(DateTime(timezone=True))
    status = Column(SQLEnum(AlertStatus))

    __table_args__ = (
        UniqueConstraint("sensor_from", "sensor_to", "alert_type", "status", name="uq_active_alert"),
    )
