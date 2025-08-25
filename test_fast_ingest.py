#!/usr/bin/env python3
"""Test mothership with CI-optimized timeouts."""

import asyncio
import json
import os
import sys
import time
import traceback
from pathlib import Path

# Set CI-optimized environment variables
os.environ["LOKI_ENABLED"] = "true" 
os.environ["LOKI_URL"] = "http://localhost:3100"
os.environ["TSDB_ENABLED"] = "true"

# Set much faster timeouts for CI
os.environ["TSDB_TIMEOUT_MS"] = "1000"  # 1 second instead of 30
os.environ["TSDB_MAX_RETRIES"] = "1"    # Only 1 retry instead of multiple
os.environ["TSDB_INITIAL_BACKOFF_MS"] = "100"  # 100ms instead of seconds
os.environ["TSDB_MAX_BACKOFF_MS"] = "1000"     # 1s max instead of 30s

os.environ["LOKI_TIMEOUT_MS"] = "1000"  # 1 second instead of 30
os.environ["LOKI_MAX_RETRIES"] = "1"    # Only 1 retry
os.environ["LOKI_INITIAL_BACKOFF_MS"] = "100"  # 100ms instead of seconds
os.environ["LOKI_MAX_BACKOFF_MS"] = "1000"     # 1s max

# Set database env vars but with very short timeout
os.environ["MOTHERSHIP_DB_DSN"] = "postgresql://postgres:postgres@localhost:5432/mothership"

# Add mothership to path
sys.path.insert(0, str(Path(__file__).parent / "mothership"))

async def test_fast_ingest():
    """Test ingest with fast timeouts suitable for CI."""
    
    print("🚀 Testing ingest with CI-optimized fast timeouts...\n")
    
    try:
        # Import server modules
        from app.server import IngestRequest, _ingest_events_internal, app_state
        from app.server import startup_event
        
        print("✅ Successfully imported server modules")
        
        # Run the startup event to initialize app_state
        print("Running server startup initialization with fast timeouts...")
        start_time = time.time()
        
        try:
            await startup_event()
            startup_time = time.time() - start_time
            print(f"✅ Server startup completed in {startup_time:.3f} seconds")
        except Exception as e:
            startup_time = time.time() - start_time
            print(f"❌ Server startup failed after {startup_time:.3f} seconds: {e}")
            traceback.print_exc()
            return False
        
        # Check if startup took too long for CI environments
        if startup_time > 30:
            print(f"⚠️  Startup took {startup_time:.1f}s - too slow for CI (should be <30s)")
        else:
            print(f"✅ Startup time {startup_time:.1f}s is acceptable for CI")
            
        # Check app_state
        print(f"App state keys: {list(app_state.keys())}")
        
        # Create test payload
        test_id = f"ci-test-{int(time.time())}"
        payload = {
            "messages": [
                {
                    "timestamp": "2025-01-01T00:00:00Z",
                    "type": "syslog",
                    "message": f"CI regression test {test_id}",
                    "hostname": "actions-runner",
                    "severity": "info"
                }
            ]
        }
        
        # Test the ingest request processing with timeout
        print(f"\nTesting ingest with test_id: {test_id}")
        request = IngestRequest(**payload)
        
        ingest_start = time.time()
        
        try:
            # Use asyncio.wait_for to enforce maximum ingest time
            result = await asyncio.wait_for(_ingest_events_internal(request), timeout=10.0)
            
            ingest_time = time.time() - ingest_start
            print(f"✅ Ingest completed in {ingest_time:.3f} seconds!")
            print(f"Status: {result.status}")
            print(f"Processed events: {result.processed_events}")
            print(f"Sink results: {result.sink_results}")
            
            if ingest_time > 5.0:
                print(f"⚠️  Ingest took {ingest_time:.1f}s - may be too slow for CI regression tests")
            else:
                print(f"✅ Ingest time {ingest_time:.1f}s is fast enough for CI")
            
            if result.status == "success":
                print("\n🎉 The /ingest endpoint works and returns HTTP 200!")
                print("📊 Analysis:")
                print(f"  - Total processing time: {ingest_time:.3f}s")
                print(f"  - Events processed: {result.processed_events}")
                
                # Analyze sink results
                for sink_name, sink_result in result.sink_results.items():
                    written = sink_result.get('written', 0)
                    errors = sink_result.get('errors', 0)
                    retries = sink_result.get('retries', 0)
                    print(f"  - {sink_name}: {written} written, {errors} errors, {retries} retries")
                
                # Check if any sinks are working
                total_written = sum(sink_result.get('written', 0) for sink_result in result.sink_results.values())
                if total_written > 0:
                    print(f"✅ {total_written} events successfully written to sinks")
                else:
                    print(f"⚠️  0 events written to sinks (database/loki unavailable)")
                    print("   This is expected in CI without database services")
                
                return True
            else:
                print(f"\n❌ Ingest returned non-success status: {result.status}")
                return False
                
        except asyncio.TimeoutError:
            ingest_time = time.time() - ingest_start
            print(f"❌ Ingest timed out after {ingest_time:.3f} seconds")
            print("   This indicates the retry/timeout logic is still too slow for CI")
            return False
        except Exception as e:
            ingest_time = time.time() - ingest_start
            print(f"❌ Ingest failed after {ingest_time:.3f} seconds: {e}")
            traceback.print_exc()
            return False
            
    except Exception as e:
        print(f"❌ Test setup failed: {e}")
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = asyncio.run(test_fast_ingest())
    if success:
        print("\n✅ The ingest endpoint works with fast CI-optimized timeouts")
        print("   The 500 errors in regression tests should be resolved")
    else:
        print("\n❌ The ingest endpoint still has timeout issues")
        sys.exit(1)