#!/usr/bin/env python3
"""
Seed traffic generator for testing the EdgeBot POC
Sends a burst of telemetry data to test anomaly detection
"""

import json
import os
import random
import requests
import time
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

CENTRAL_API_BASE = os.getenv("CENTRAL_API_BASE", "http://localhost:8000")


def create_test_telemetry(edge_id: str, add_anomaly: bool = False):
    """Create test telemetry data"""
    metrics = {
        'cpu_percent': random.uniform(30, 70),
        'memory_percent': random.uniform(40, 80),
        'temperature': random.uniform(25, 45),
        'network_latency_ms': random.uniform(5, 20),
        'status': random.choice(['healthy', 'warning']),
        'node_type': 'edge',
        'uptime_hours': random.randint(1, 100)
    }
    
    # Add anomalous values to trigger detection
    if add_anomaly:
        anomaly_type = random.choice(['cpu_spike', 'temp_spike', 'latency_spike'])
        if anomaly_type == 'cpu_spike':
            metrics['cpu_percent'] = random.uniform(85, 95)
        elif anomaly_type == 'temp_spike':
            metrics['temperature'] = random.uniform(65, 75)
        elif anomaly_type == 'latency_spike':
            metrics['network_latency_ms'] = random.uniform(80, 120)
    
    return {
        'edge_id': edge_id,
        'ts': datetime.now(timezone.utc).isoformat(),
        'metrics': metrics
    }


def send_telemetry(telemetry_data):
    """Send telemetry to central platform"""
    try:
        response = requests.post(
            f"{CENTRAL_API_BASE}/ingest",
            json=telemetry_data,
            timeout=10
        )
        return response.status_code == 200
    except Exception as e:
        print(f"Error sending telemetry: {e}")
        return False


def main():
    print(f"EdgeBot Seed Traffic Generator")
    print(f"Central API: {CENTRAL_API_BASE}")
    print()
    
    # Test central platform connectivity
    try:
        response = requests.get(f"{CENTRAL_API_BASE}/healthz", timeout=5)
        if response.status_code != 200:
            print("ERROR: Central platform is not healthy!")
            return
        print("✓ Central platform is healthy")
    except Exception as e:
        print(f"ERROR: Cannot connect to central platform: {e}")
        return
    
    edge_ids = ['test-edge-1', 'test-edge-2', 'test-edge-3']
    
    # Send normal traffic first to establish baselines
    print("\n🔄 Sending baseline traffic...")
    for i in range(20):
        for edge_id in edge_ids:
            telemetry = create_test_telemetry(edge_id, add_anomaly=False)
            success = send_telemetry(telemetry)
            print(f"  {edge_id}: {'✓' if success else '✗'}")
        time.sleep(0.5)
    
    # Send some anomalous traffic
    print("\n⚠️  Sending anomalous traffic...")
    for i in range(5):
        for edge_id in edge_ids:
            # 70% chance of anomaly
            add_anomaly = random.random() < 0.7
            telemetry = create_test_telemetry(edge_id, add_anomaly=add_anomaly)
            success = send_telemetry(telemetry)
            status = "ANOMALY" if add_anomaly else "NORMAL"
            print(f"  {edge_id} ({status}): {'✓' if success else '✗'}")
        time.sleep(1)
    
    # Check results
    print("\n📊 Checking results...")
    try:
        # Get metrics
        metrics_response = requests.get(f"{CENTRAL_API_BASE}/metrics", timeout=5)
        if metrics_response.status_code == 200:
            metrics = metrics_response.json()
            print(f"  Total ingested records: {metrics['ingested_count']}")
            if metrics['last_ingest_ts']:
                print(f"  Last ingest: {metrics['last_ingest_ts']}")
        
        # Get anomalies
        anomalies_response = requests.get(f"{CENTRAL_API_BASE}/anomalies", timeout=5)
        if anomalies_response.status_code == 200:
            anomalies = anomalies_response.json()
            print(f"  Detected anomalies: {anomalies['count']}")
            
            if anomalies['count'] > 0:
                print("\n  Recent anomalies:")
                for anomaly in anomalies['anomalies'][:5]:  # Show first 5
                    print(f"    {anomaly['edge_id']}: {anomaly['metric_name']}="
                          f"{anomaly['metric_value']} (z-score: {anomaly['z_score']:.2f})")
    
    except Exception as e:
        print(f"  Error checking results: {e}")
    
    print("\n🎉 Seed traffic generation complete!")
    print(f"   View all data at: {CENTRAL_API_BASE}/docs")


if __name__ == "__main__":
    main()