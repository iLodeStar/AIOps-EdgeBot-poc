import pytest
from fastapi.testclient import TestClient
import sys
import os

# Add the project root to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from central_platform.app.main import app

client = TestClient(app)


def test_health_check():
    """Test the health check endpoint"""
    response = client.get("/healthz")
    assert response.status_code == 200
    
    data = response.json()
    assert data["status"] == "ok"


def test_metrics_endpoint():
    """Test the metrics endpoint returns expected structure"""
    response = client.get("/metrics")
    assert response.status_code == 200
    
    data = response.json()
    assert "ingested_count" in data
    assert "last_ingest_ts" in data
    assert isinstance(data["ingested_count"], int)


def test_anomalies_endpoint():
    """Test the anomalies endpoint returns expected structure"""
    response = client.get("/anomalies")
    assert response.status_code == 200
    
    data = response.json()
    assert "anomalies" in data
    assert "count" in data
    assert isinstance(data["anomalies"], list)
    assert isinstance(data["count"], int)


def test_ingest_telemetry():
    """Test telemetry ingestion"""
    telemetry_data = {
        "edge_id": "test-edge-1",
        "ts": "2024-01-01T12:00:00Z",
        "metrics": {
            "cpu_percent": 45.5,
            "memory_percent": 60.0,
            "temperature": 35.0,
            "status": "healthy"
        }
    }
    
    response = client.post("/ingest", json=telemetry_data)
    assert response.status_code == 200
    
    data = response.json()
    assert data["status"] == "ok"


def test_ingest_invalid_telemetry():
    """Test telemetry ingestion with invalid data"""
    # Missing required fields
    invalid_data = {
        "edge_id": "test-edge-1",
        "metrics": {"cpu": 50}
        # Missing 'ts' field
    }
    
    response = client.post("/ingest", json=invalid_data)
    assert response.status_code == 422  # Validation error