#!/usr/bin/env python3
"""Test Loki connectivity and sink behavior."""

import asyncio
import httpx
import os
import sys
from pathlib import Path

# Add mothership to path
sys.path.insert(0, str(Path(__file__).parent / "mothership"))

async def test_loki_connectivity():
    """Test if we can connect to Loki."""
    print("Testing Loki connectivity...")
    
    loki_url = "http://localhost:3100"
    
    try:
        async with httpx.AsyncClient() as client:
            # Test Loki health endpoint
            response = await client.get(f"{loki_url}/ready", timeout=5.0)
            print(f"Loki ready endpoint: {response.status_code}")
            if response.status_code != 200:
                print(f"Loki not ready: {response.text}")
                return False
                
            # Test Loki ingestion endpoint
            test_data = {
                "streams": [
                    {
                        "stream": {"source": "mothership", "level": "info"},
                        "values": [
                            ["1640995200000000000", "Test message"]
                        ]
                    }
                ]
            }
            
            response = await client.post(f"{loki_url}/loki/api/v1/push", 
                                        json=test_data, 
                                        headers={"Content-Type": "application/json"},
                                        timeout=10.0)
            print(f"Loki push test: {response.status_code}")
            if response.status_code not in [200, 204]:
                print(f"Loki push failed: {response.text}")
                return False
                
            print("✅ Loki is accessible")
            return True
            
    except Exception as e:
        print(f"❌ Loki connection failed: {e}")
        return False

async def test_loki_client():
    """Test the Loki client directly."""
    print("\nTesting LokiClient...")
    
    try:
        from app.storage.loki import LokiClient
        
        config = {
            "enabled": True,
            "url": "http://localhost:3100",
            "batch_size": 10,
            "batch_timeout_seconds": 1.0,
        }
        
        client = LokiClient(config)
        await client.start()
        
        # Test event conversion
        test_event = {
            "timestamp": "2025-01-01T00:00:00Z",
            "message": "Test message for Loki",
            "type": "syslog",
            "hostname": "test-host",
            "severity": "info"
        }
        
        result = await client.write_events([test_event])
        print(f"LokiClient write result: {result}")
        
        await client.stop()
        print("✅ LokiClient test successful")
        return True
        
    except Exception as e:
        print(f"❌ LokiClient test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_sink_manager():
    """Test SinksManager without database."""
    print("\nTesting SinksManager with Loki only...")
    
    try:
        from app.storage.sinks import SinksManager
        
        # Test config with Loki only (no database)
        config = {
            "sinks": {
                "timescaledb": {"enabled": False},  # Disable TSDB
                "loki": {
                    "enabled": True,
                    "url": "http://localhost:3100",
                    "batch_size": 10,
                    "batch_timeout_seconds": 1.0,
                }
            }
        }
        
        sinks_manager = SinksManager(config, tsdb_writer=None)
        print(f"SinksManager created with sinks: {list(sinks_manager.sinks.keys())}")
        
        await sinks_manager.start()
        print("SinksManager started")
        
        # Test event writing
        test_events = [{
            "timestamp": "2025-01-01T00:00:00Z",
            "message": "Test message for SinksManager",
            "type": "syslog", 
            "hostname": "test-host",
            "severity": "info"
        }]
        
        result = await sinks_manager.write_events(test_events)
        print(f"SinksManager write result: {result}")
        
        await sinks_manager.stop()
        print("✅ SinksManager test successful")
        return True
        
    except Exception as e:
        print(f"❌ SinksManager test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def main():
    """Run all tests."""
    print("🔍 Debugging Loki integration issues...\n")
    
    success = True
    
    # Test 1: Basic Loki connectivity
    if not await test_loki_connectivity():
        print("❌ Loki is not accessible - this might be the root cause")
        success = False
        
    # Test 2: LokiClient functionality
    if not await test_loki_client():
        print("❌ LokiClient has issues")
        success = False
        
    # Test 3: SinksManager functionality  
    if not await test_sink_manager():
        print("❌ SinksManager has issues")
        success = False
        
    if success:
        print("\n🎉 All tests passed - Loki integration should work!")
    else:
        print("\n❌ Some tests failed - found issues with Loki integration")
        
    return success

if __name__ == "__main__":
    success = asyncio.run(main())
    if not success:
        sys.exit(1)