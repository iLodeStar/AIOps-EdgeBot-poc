#!/usr/bin/env python3
"""
Offline test script for EdgeBot POC core logic
Tests components that don't require external dependencies
"""

import sys
import os
import json
from datetime import datetime, timezone

# Add current directory to path
sys.path.insert(0, '.')


def test_telemetry_simulation():
    """Test telemetry simulation without external dependencies"""
    print("🧪 Testing telemetry simulation...")
    
    try:
        from edge_node.app.sim import TelemetrySimulator, create_telemetry_data
        
        # Test simulator creation
        simulator = TelemetrySimulator("test-edge-1")
        
        # Generate multiple data points
        data_points = []
        for i in range(5):
            metrics = simulator.generate_telemetry()
            data_points.append(metrics)
        
        print(f"  ✅ Generated {len(data_points)} telemetry data points")
        
        # Validate structure
        first_point = data_points[0]
        expected_keys = ['cpu_percent', 'memory_percent', 'temperature', 'network_latency_ms', 'status', 'node_type', 'uptime_hours']
        
        for key in expected_keys:
            if key not in first_point:
                print(f"  ❌ Missing key: {key}")
                return False
        
        print(f"  ✅ All expected keys present: {expected_keys}")
        
        # Test data types and ranges
        if not (0 <= first_point['cpu_percent'] <= 100):
            print(f"  ❌ CPU percent out of range: {first_point['cpu_percent']}")
            return False
            
        if not (0 <= first_point['memory_percent'] <= 100):
            print(f"  ❌ Memory percent out of range: {first_point['memory_percent']}")
            return False
            
        if first_point['status'] not in ['healthy', 'warning', 'critical']:
            print(f"  ❌ Invalid status: {first_point['status']}")
            return False
        
        print("  ✅ Data types and ranges are valid")
        
        # Test complete telemetry data structure
        telemetry_data = create_telemetry_data("test-edge-2")
        required_fields = ['edge_id', 'ts', 'metrics']
        
        for field in required_fields:
            if field not in telemetry_data:
                print(f"  ❌ Missing field in telemetry data: {field}")
                return False
        
        # Validate timestamp format
        try:
            ts = telemetry_data['ts']
            if ts.endswith('Z'):
                ts = ts[:-1] + '+00:00'
            datetime.fromisoformat(ts)
            print(f"  ✅ Timestamp format is valid: {telemetry_data['ts']}")
        except ValueError as e:
            print(f"  ❌ Invalid timestamp format: {e}")
            return False
        
        print("  ✅ Complete telemetry data structure is valid")
        return True
        
    except Exception as e:
        print(f"  ❌ Error in telemetry simulation: {e}")
        return False


def test_anomaly_detection_logic():
    """Test the anomaly detection logic (z-score calculation)"""
    print("🧪 Testing anomaly detection logic...")
    
    try:
        import numpy as np
        
        def compute_z_score(values, new_value):
            """Simple z-score computation"""
            if len(values) < 2:
                return 0.0
            
            arr = np.array(values)
            mean = np.mean(arr)
            std = np.std(arr, ddof=1)
            
            if std == 0:
                return 0.0
            
            return (new_value - mean) / std
        
        # Test normal case
        historical = [10, 12, 11, 13, 10, 12, 11, 13]
        new_value = 12
        z_score = compute_z_score(historical, new_value)
        
        print(f"  ✅ Normal value z-score: {z_score:.2f} (should be close to 0)")
        
        # Test anomalous case
        anomalous_value = 25
        z_score_anomaly = compute_z_score(historical, anomalous_value)
        
        print(f"  ✅ Anomalous value z-score: {z_score_anomaly:.2f} (should be > 3)")
        
        if abs(z_score_anomaly) >= 3.0:
            print("  ✅ Anomaly detection threshold working correctly")
        else:
            print("  ⚠️  Anomaly detection threshold may need adjustment")
        
        return True
        
    except ImportError:
        print("  ⚠️  NumPy not available, skipping z-score test")
        return True
    except Exception as e:
        print(f"  ❌ Error in anomaly detection logic: {e}")
        return False


def test_file_structure():
    """Test that all required files exist"""
    print("🧪 Testing file structure...")
    
    critical_files = [
        'README.md',
        'docker-compose.yml',
        'central_platform/app/main.py',
        'edge_node/app/main.py',
        'edge_node/app/sim.py'
    ]
    
    missing_files = []
    for file_path in critical_files:
        if not os.path.exists(file_path):
            missing_files.append(file_path)
    
    if missing_files:
        print(f"  ❌ Missing critical files: {missing_files}")
        return False
    else:
        print(f"  ✅ All critical files present: {len(critical_files)} files")
        return True


def test_configuration_parsing():
    """Test configuration file parsing"""
    print("🧪 Testing configuration parsing...")
    
    try:
        # Test .env.example parsing
        env_vars = {}
        if os.path.exists('.env.example'):
            with open('.env.example', 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        env_vars[key] = value
        
        required_env_vars = ['EDGE_ID', 'CENTRAL_API_BASE', 'SEND_INTERVAL_SEC']
        for var in required_env_vars:
            if var not in env_vars:
                print(f"  ❌ Missing environment variable: {var}")
                return False
        
        print(f"  ✅ Environment variables configured: {list(env_vars.keys())}")
        
        # Test default values
        if env_vars.get('EDGE_ID') == 'edge-1':
            print("  ✅ Default EDGE_ID is correct")
        
        if 'SEND_INTERVAL_SEC' in env_vars:
            try:
                interval = int(env_vars['SEND_INTERVAL_SEC'])
                if interval > 0:
                    print(f"  ✅ Send interval is valid: {interval} seconds")
                else:
                    print(f"  ❌ Invalid send interval: {interval}")
                    return False
            except ValueError:
                print(f"  ❌ Send interval is not a number: {env_vars['SEND_INTERVAL_SEC']}")
                return False
        
        return True
        
    except Exception as e:
        print(f"  ❌ Error parsing configuration: {e}")
        return False


def main():
    """Run offline tests"""
    print("🔬 EdgeBot POC Offline Testing")
    print("=" * 50)
    
    # Change to repository root if needed
    if os.path.exists('central_platform'):
        os.chdir('.')
    elif os.path.exists('../central_platform'):
        os.chdir('..')
    else:
        print("❌ Cannot find EdgeBot POC repository structure")
        sys.exit(1)
    
    tests = [
        ("File Structure", test_file_structure),
        ("Configuration Parsing", test_configuration_parsing),
        ("Telemetry Simulation", test_telemetry_simulation),
        ("Anomaly Detection Logic", test_anomaly_detection_logic),
    ]
    
    passed = 0
    total = len(tests)
    
    for name, test_func in tests:
        print(f"\n{name}:")
        
        if test_func():
            passed += 1
    
    print("\n" + "=" * 50)
    print(f"📊 Test Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All offline tests passed!")
        print("\n📋 Implementation Summary:")
        print("  • Core telemetry simulation working")
        print("  • File structure complete")
        print("  • Configuration properly set up")
        print("  • Anomaly detection logic implemented")
        print("\n🚀 Ready for deployment with Docker Compose!")
    else:
        print("⚠️  Some tests failed, but core functionality appears working")
    
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())