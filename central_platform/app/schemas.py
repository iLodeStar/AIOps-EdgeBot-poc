from typing import Dict, Union, List, Optional
from datetime import datetime
from pydantic import BaseModel, field_validator


class TelemetryIngest(BaseModel):
    edge_id: str
    ts: str  # RFC3339 timestamp string
    metrics: Dict[str, Union[float, str, int]]

    @field_validator('edge_id')
    @classmethod
    def validate_edge_id(cls, v):
        if not v or not v.strip():
            raise ValueError('edge_id cannot be empty')
        return v.strip()


class HealthResponse(BaseModel):
    status: str


class AnomalyResponse(BaseModel):
    id: int
    edge_id: str
    metric_name: str
    metric_value: float
    z_score: float
    ts: datetime
    detected_at: datetime


class MetricsResponse(BaseModel):
    ingested_count: int
    last_ingest_ts: Optional[str] = None


class AnomaliesListResponse(BaseModel):
    anomalies: List[AnomalyResponse]
    count: int