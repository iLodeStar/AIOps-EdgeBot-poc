#!/usr/bin/env python3
"""Simple script to test mothership ingestion locally."""

import json
import requests
import time
import os

# Set environment variables as in the workflow
os.environ["LOKI_ENABLED"] = "true" 
os.environ["LOKI_URL"] = "http://localhost:3100"
os.environ["TSDB_ENABLED"] = "true"
os.environ["TSDB_HOST"] = "localhost"
os.environ["TSDB_PORT"] = "5432"
os.environ["TSDB_DATABASE"] = "mothership"
os.environ["TSDB_USERNAME"] = "postgres"
os.environ["TSDB_PASSWORD"] = "postgres"
os.environ["MOTHERSHIP_DB_DSN"] = "postgresql://postgres:postgres@localhost:5432/mothership"

def test_ingestion():
    """Test the mothership ingestion endpoint."""
    
    # Test data matching the workflow
    test_id = f"test-{int(time.time())}"
    payload = {
        "messages": [
            {
                "timestamp": "2025-01-01T00:00:00Z",
                "type": "syslog", 
                "message": f"Full regression test via GitHub Actions {test_id}",
                "hostname": "actions-runner",
                "severity": "info",
                "_internal": "should_be_dropped",
                "raw_message": "<14>Jan  1 00:00:00 actions app: Full regression test",
                "tags": {"component":"regression","path":"edge->mothership","channel":"ci"}
            }
        ]
    }
    
    try:
        # First check health
        health_resp = requests.get("http://localhost:8443/healthz", timeout=5)
        print(f"Health check: {health_resp.status_code}")
        if health_resp.status_code == 200:
            print(f"Health response: {health_resp.json()}")
        else:
            print(f"Health error: {health_resp.text}")
            return
            
    except Exception as e:
        print(f"Health check failed: {e}")
        print("Make sure mothership is running on localhost:8443")
        return
    
    try:
        # Test ingestion
        print(f"Testing ingestion with test_id: {test_id}")
        resp = requests.post(
            "http://localhost:8443/ingest",
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        
        print(f"Ingestion status: {resp.status_code}")
        print(f"Response: {resp.text}")
        
        if resp.status_code == 200:
            result = resp.json()
            print(f"Successfully ingested {result.get('processed_events', 0)} events")
            print(f"Sink results: {result.get('sink_results', {})}")
        else:
            print(f"Ingestion failed with {resp.status_code}: {resp.text}")
            
    except Exception as e:
        print(f"Ingestion test failed: {e}")

if __name__ == "__main__":
    test_ingestion()