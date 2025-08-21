from datetime import datetime
from sqlalchemy import Column, String, Float, Integer, DateTime, Text, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

Base = declarative_base()


class TelemetryRecord(Base):
    __tablename__ = "telemetry_records"
    
    id = Column(Integer, primary_key=True, index=True)
    edge_id = Column(String, nullable=False, index=True)
    ts = Column(DateTime, nullable=False, index=True)
    metrics = Column(Text, nullable=False)  # JSON string
    created_at = Column(DateTime, default=datetime.utcnow)


class AnomalyRecord(Base):
    __tablename__ = "anomaly_records"
    
    id = Column(Integer, primary_key=True, index=True)
    edge_id = Column(String, nullable=False, index=True)
    metric_name = Column(String, nullable=False)
    metric_value = Column(Float, nullable=False)
    z_score = Column(Float, nullable=False)
    ts = Column(DateTime, nullable=False)
    detected_at = Column(DateTime, default=datetime.utcnow, index=True)


def get_database_url():
    return "sqlite:///./data/central.db"


def create_database_engine():
    engine = create_engine(
        get_database_url(),
        connect_args={"check_same_thread": False}
    )
    return engine


def create_tables(engine):
    Base.metadata.create_all(bind=engine)


def get_session_factory(engine):
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)