#!/usr/bin/env python3
"""Test mothership server startup and ingest endpoint locally."""

import asyncio
import json
import os
import sys
import time
import traceback
from pathlib import Path

# Set environment exactly as in regression test
os.environ["LOKI_ENABLED"] = "true" 
os.environ["LOKI_URL"] = "http://localhost:3100"
os.environ["TSDB_ENABLED"] = "true"
os.environ["TSDB_HOST"] = "localhost"
os.environ["TSDB_PORT"] = "5432"
os.environ["TSDB_DATABASE"] = "mothership"
os.environ["TSDB_USERNAME"] = "postgres"
os.environ["TSDB_PASSWORD"] = "postgres"
os.environ["MOTHERSHIP_DB_DSN"] = "postgresql://postgres:postgres@localhost:5432/mothership"

# Add mothership to path
sys.path.insert(0, str(Path(__file__).parent / "mothership"))

async def test_ingest_endpoint_directly():
    """Test the ingest endpoint logic directly to isolate the 500 error."""
    
    print("🧪 Testing ingest endpoint logic directly...\n")
    
    try:
        # Import server modules
        from app.server import IngestRequest, _ingest_events_internal, app_state
        from app.server import startup_event
        
        print("✅ Successfully imported server modules")
        
        # Run the startup event to initialize app_state
        print("Running server startup initialization...")
        try:
            await startup_event()
            print("✅ Server startup completed successfully")
        except Exception as e:
            print(f"❌ Server startup failed: {e}")
            traceback.print_exc()
            return False
            
        # Check app_state
        print(f"App state keys: {list(app_state.keys())}")
        print(f"Pipeline: {app_state.get('pipeline') is not None}")
        print(f"SinksManager: {app_state.get('sinks_manager') is not None}")
        print(f"TSDB writer: {app_state.get('tsdb_writer') is not None}")
        
        # Create test payload exactly like regression test
        test_id = f"test-ingest-{int(time.time())}"
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
        
        # Test the ingest request processing
        print(f"\nTesting ingest with test_id: {test_id}")
        request = IngestRequest(**payload)
        
        try:
            # Call the internal ingest function directly
            result = await _ingest_events_internal(request)
            
            print(f"✅ Ingest completed successfully!")
            print(f"Status: {result.status}")
            print(f"Processed events: {result.processed_events}")
            print(f"Processing time: {result.processing_time:.3f}s")
            print(f"Sink results: {result.sink_results}")
            
            if result.status == "success":
                print("\n🎉 The /ingest endpoint would return HTTP 200 (not 500)!")
                return True
            else:
                print(f"\n❌ Ingest returned non-success status: {result.status}")
                return False
                
        except Exception as e:
            print(f"❌ Ingest processing failed: {e}")
            traceback.print_exc()
            return False
            
    except Exception as e:
        print(f"❌ Test setup failed: {e}")
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = asyncio.run(test_ingest_endpoint_directly())
    if success:
        print("\n✅ The ingest endpoint should work without 500 errors")
    else:
        print("\n❌ The ingest endpoint has issues causing 500 errors")
        sys.exit(1)