#!/usr/bin/env python3
"""
Validation script for EdgeBot POC implementation
Tests core functionality without requiring external dependencies
"""

import json
import os
import sys
from datetime import datetime, timezone


def validate_file_structure():
    """Validate that all required files exist"""
    required_files = [
        'README.md',
        'docker-compose.yml', 
        '.env.example',
        'Makefile',
        '.pre-commit-config.yaml',
        'central_platform/requirements.txt',
        'central_platform/Dockerfile',
        'central_platform/app/main.py',
        'central_platform/app/models.py', 
        'central_platform/app/schemas.py',
        'edge_node/requirements.txt',
        'edge_node/Dockerfile',
        'edge_node/app/main.py',
        'edge_node/app/sim.py',
        'scripts/dev_up.sh',
        'scripts/dev_down.sh',
        'scripts/dev_logs.sh',
        'scripts/seed_traffic.py',
        'tests/test_central_healthz.py'
    ]
    
    missing_files = []
    for file_path in required_files:
        if not os.path.exists(file_path):
            missing_files.append(file_path)
    
    return missing_files


def validate_telemetry_simulation():
    """Validate the telemetry simulation logic"""
    sys.path.insert(0, '.')
    try:
        from edge_node.app.sim import TelemetrySimulator, create_telemetry_data
        
        # Test simulator creation
        simulator = TelemetrySimulator("test-edge")
        
        # Test telemetry generation
        metrics = simulator.generate_telemetry()
        
        # Validate required metrics exist
        required_metrics = ['cpu_percent', 'memory_percent', 'temperature', 'network_latency_ms']
        for metric in required_metrics:
            if metric not in metrics:
                return f"Missing required metric: {metric}"
        
        # Validate metric ranges
        if not (0 <= metrics['cpu_percent'] <= 100):
            return f"CPU percent out of range: {metrics['cpu_percent']}"
        
        if not (0 <= metrics['memory_percent'] <= 100):
            return f"Memory percent out of range: {metrics['memory_percent']}"
        
        # Test complete telemetry data creation
        telemetry_data = create_telemetry_data("test-edge")
        
        # Validate structure
        required_fields = ['edge_id', 'ts', 'metrics']
        for field in required_fields:
            if field not in telemetry_data:
                return f"Missing required field: {field}"
        
        # Validate timestamp format
        try:
            datetime.fromisoformat(telemetry_data['ts'].replace('Z', '+00:00'))
        except ValueError:
            return f"Invalid timestamp format: {telemetry_data['ts']}"
            
        return None  # Success
        
    except Exception as e:
        return f"Telemetry simulation error: {str(e)}"


def validate_pydantic_schemas():
    """Validate Pydantic schemas can be imported and instantiated"""
    sys.path.insert(0, '.')
    try:
        from central_platform.app.schemas import (
            TelemetryIngest, HealthResponse, AnomalyResponse, 
            MetricsResponse, AnomaliesListResponse
        )
        
        # Test TelemetryIngest schema
        test_data = {
            "edge_id": "test-edge",
            "ts": "2024-01-01T12:00:00Z",
            "metrics": {
                "cpu_percent": 45.5,
                "memory_percent": 60.0,
                "status": "healthy"
            }
        }
        
        telemetry = TelemetryIngest(**test_data)
        if telemetry.edge_id != "test-edge":
            return "TelemetryIngest validation failed"
        
        # Test HealthResponse
        health = HealthResponse(status="ok")
        if health.status != "ok":
            return "HealthResponse validation failed"
        
        return None  # Success
        
    except Exception as e:
        return f"Schema validation error: {str(e)}"


def validate_configuration_files():
    """Validate configuration files are properly formatted"""
    try:
        # Validate .env.example
        with open('.env.example', 'r') as f:
            env_content = f.read()
            if 'EDGE_ID=' not in env_content:
                return ".env.example missing EDGE_ID"
            if 'CENTRAL_API_BASE=' not in env_content:
                return ".env.example missing CENTRAL_API_BASE"
        
        # Validate docker-compose.yml
        with open('docker-compose.yml', 'r') as f:
            compose_content = f.read()
            if 'central:' not in compose_content:
                return "docker-compose.yml missing central service"
            if 'edge:' not in compose_content:
                return "docker-compose.yml missing edge service"
        
        return None  # Success
        
    except Exception as e:
        return f"Configuration file error: {str(e)}"


def main():
    """Run all validations"""
    print("🔍 EdgeBot POC Implementation Validation")
    print("=" * 50)
    
    # Change to repository root if needed
    if os.path.exists('central_platform'):
        os.chdir('.')
    elif os.path.exists('../central_platform'):
        os.chdir('..')
    else:
        print("❌ Cannot find EdgeBot POC repository structure")
        sys.exit(1)
    
    validations = [
        ("File Structure", validate_file_structure),
        ("Telemetry Simulation", validate_telemetry_simulation),
        ("Pydantic Schemas", validate_pydantic_schemas),
        ("Configuration Files", validate_configuration_files),
    ]
    
    passed = 0
    total = len(validations)
    
    for name, validation_func in validations:
        print(f"\n📋 {name}:")
        
        result = validation_func()
        if result is None or (isinstance(result, list) and len(result) == 0):
            print("  ✅ PASSED")
            passed += 1
        else:
            print(f"  ❌ FAILED: {result}")
    
    print("\n" + "=" * 50)
    print(f"📊 Results: {passed}/{total} validations passed")
    
    if passed == total:
        print("🎉 All validations passed! EdgeBot POC implementation is ready.")
        print("\n📖 Next steps:")
        print("  1. Copy .env.example to .env")
        print("  2. Run 'docker compose up --build' or 'make up'")
        print("  3. Test endpoints at http://localhost:8000/docs")
        print("  4. Generate test data with 'make seed'")
    else:
        print("🚨 Some validations failed. Please review the implementation.")
        sys.exit(1)


if __name__ == "__main__":
    main()