import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import numpy as np
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from .models import (
    TelemetryRecord, 
    AnomalyRecord, 
    create_database_engine, 
    create_tables, 
    get_session_factory
)
from .schemas import (
    TelemetryIngest, 
    HealthResponse, 
    AnomalyResponse, 
    MetricsResponse, 
    AnomaliesListResponse
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="AIOps EdgeBot Central Platform",
    description="Central platform for collecting telemetry and detecting anomalies from edge nodes",
    version="1.0.0"
)

# Add CORS middleware for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database setup
engine = None
SessionLocal = None


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.on_event("startup")
async def startup_event():
    global engine, SessionLocal
    logger.info("Starting up Central Platform...")
    
    # Ensure data directory exists
    data_dir = Path("./data")
    data_dir.mkdir(exist_ok=True)
    
    # Create database engine and tables
    engine = create_database_engine()
    create_tables(engine)
    SessionLocal = get_session_factory(engine)
    
    logger.info("Central Platform started successfully")


def parse_rfc3339_timestamp(ts_str: str) -> datetime:
    """Parse RFC3339 timestamp string to datetime object"""
    try:
        # Handle both with and without 'Z' suffix
        if ts_str.endswith('Z'):
            ts_str = ts_str[:-1] + '+00:00'
        return datetime.fromisoformat(ts_str)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid timestamp format: {ts_str}")


def compute_z_score(values: List[float], new_value: float) -> float:
    """Compute z-score for a new value given historical values"""
    if len(values) < 2:
        return 0.0
    
    arr = np.array(values)
    mean = np.mean(arr)
    std = np.std(arr, ddof=1)
    
    if std == 0:
        return 0.0
    
    return (new_value - mean) / std


def detect_anomalies(db: Session, edge_id: str, ts: datetime, metrics: dict):
    """Detect anomalies using rolling z-score and store anomaly records"""
    K = 10  # Number of historical values to consider
    Z_THRESHOLD = 3.0
    
    for metric_name, metric_value in metrics.items():
        # Skip non-numeric metrics
        if not isinstance(metric_value, (int, float)):
            continue
        
        # Get last K values for this metric and edge
        historical_records = db.query(TelemetryRecord).filter(
            TelemetryRecord.edge_id == edge_id,
            TelemetryRecord.ts < ts
        ).order_by(TelemetryRecord.ts.desc()).limit(K).all()
        
        historical_values = []
        for record in historical_records:
            try:
                record_metrics = json.loads(record.metrics)
                if metric_name in record_metrics:
                    val = record_metrics[metric_name]
                    if isinstance(val, (int, float)):
                        historical_values.append(float(val))
            except (json.JSONDecodeError, KeyError, ValueError):
                continue
        
        # Compute z-score
        z_score = compute_z_score(historical_values, float(metric_value))
        
        # Check for anomaly
        if abs(z_score) >= Z_THRESHOLD:
            anomaly = AnomalyRecord(
                edge_id=edge_id,
                metric_name=metric_name,
                metric_value=float(metric_value),
                z_score=z_score,
                ts=ts
            )
            db.add(anomaly)
            logger.info(f"Anomaly detected: {edge_id} {metric_name}={metric_value} z_score={z_score:.2f}")


@app.get("/healthz", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    return HealthResponse(status="ok")


@app.post("/ingest")
async def ingest_telemetry(telemetry: TelemetryIngest, db: Session = Depends(get_db)):
    """Ingest telemetry data from edge nodes"""
    try:
        # Parse timestamp
        ts = parse_rfc3339_timestamp(telemetry.ts)
        
        # Store telemetry record
        record = TelemetryRecord(
            edge_id=telemetry.edge_id,
            ts=ts,
            metrics=json.dumps(telemetry.metrics)
        )
        db.add(record)
        
        # Detect anomalies
        detect_anomalies(db, telemetry.edge_id, ts, telemetry.metrics)
        
        db.commit()
        
        logger.info(f"Ingested telemetry from {telemetry.edge_id} at {telemetry.ts}")
        return {"status": "ok", "message": "Telemetry ingested successfully"}
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error ingesting telemetry: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error ingesting telemetry: {str(e)}")


@app.get("/anomalies", response_model=AnomaliesListResponse)
async def get_anomalies(limit: int = 100, db: Session = Depends(get_db)):
    """Get recent anomalies"""
    try:
        anomalies = db.query(AnomalyRecord).order_by(
            AnomalyRecord.detected_at.desc()
        ).limit(limit).all()
        
        anomaly_responses = [
            AnomalyResponse(
                id=anomaly.id,
                edge_id=anomaly.edge_id,
                metric_name=anomaly.metric_name,
                metric_value=anomaly.metric_value,
                z_score=anomaly.z_score,
                ts=anomaly.ts,
                detected_at=anomaly.detected_at
            )
            for anomaly in anomalies
        ]
        
        return AnomaliesListResponse(
            anomalies=anomaly_responses,
            count=len(anomaly_responses)
        )
        
    except Exception as e:
        logger.error(f"Error retrieving anomalies: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error retrieving anomalies: {str(e)}")


@app.get("/metrics", response_model=MetricsResponse)
async def get_metrics(db: Session = Depends(get_db)):
    """Get service metrics"""
    try:
        # Count total ingested records
        ingested_count = db.query(TelemetryRecord).count()
        
        # Get last ingest timestamp
        last_record = db.query(TelemetryRecord).order_by(
            TelemetryRecord.created_at.desc()
        ).first()
        
        last_ingest_ts = None
        if last_record:
            last_ingest_ts = last_record.created_at.isoformat()
        
        return MetricsResponse(
            ingested_count=ingested_count,
            last_ingest_ts=last_ingest_ts
        )
        
    except Exception as e:
        logger.error(f"Error retrieving metrics: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error retrieving metrics: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)