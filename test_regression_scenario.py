#!/usr/bin/env python3
"""Test that simulates the exact regression test scenario."""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

# Add mothership to path
sys.path.insert(0, str(Path(__file__).parent / "mothership"))

# Set environment exactly like the regression pipeline
os.environ["LOKI_ENABLED"] = "true"
os.environ["LOKI_URL"] = "http://localhost:3100"
os.environ["GITHUB_ACTIONS"] = "true"
os.environ["MOTHERSHIP_LOG_LEVEL"] = "INFO"
os.environ["TSDB_ENABLED"] = "false"  # Focus on Loki only

from mothership.app.server import app_state
from mothership.app.config import ConfigManager
from mothership.app.storage.sinks import SinksManager
from mothership.app.server import IngestRequest
from mothership.app.storage.loki import LokiClient

# Mock HTTP for successful Loki response
import httpx
from unittest.mock import Mock, AsyncMock


async def test_regression_scenario():
    """Test the exact regression test scenario with CI immediate flush."""
    print("🎯 Testing Regression Test Scenario")
    print("=" * 50)
    
    # 1. Load config like the server does
    print("1️⃣ Loading configuration...")
    config_manager = ConfigManager()
    config = config_manager.load_config()
    print(f"✅ Enabled sinks: {config_manager.get_enabled_sinks()}")
    
    # 2. Create sinks manager
    print("2️⃣ Creating SinksManager...")
    sinks_manager = SinksManager(config, tsdb_writer=None)
    print(f"✅ Sink names: {sinks_manager.get_sink_names()}")
    
    # 3. Mock the Loki HTTP client for success
    print("3️⃣ Setting up mock HTTP client...")
    loki_sink = sinks_manager.get_sink("loki")
    if not loki_sink:
        print("❌ No Loki sink found!")
        return False
        
    # Start the sinks to initialize HTTP clients
    await sinks_manager.start()
    
    # Mock the underlying Loki client's HTTP client
    mock_response = Mock()
    mock_response.status_code = 204
    mock_http_client = AsyncMock()
    mock_http_client.post.return_value = mock_response
    
    # Access the underlying LokiClient and replace its HTTP client
    loki_client = loki_sink.sink.client  # ResilientSink -> LokiSink -> LokiClient
    loki_client.client = mock_http_client
    
    print(f"✅ Mock HTTP client configured")
    print(f"✅ CI flush enabled: {loki_client._is_ci_environment()}")
    
    # 4. Create the exact test payload from regression test
    print("4️⃣ Creating test payload...")
    test_id = f"regress-{int(time.time())}"
    events = [{
        "timestamp": "2025-01-01T00:00:00Z",
        "type": "syslog",
        "message": f"Full regression test via GitHub Actions {test_id}",
        "hostname": "actions-runner",
        "severity": "info",
        "_internal": "should_be_dropped",
        "raw_message": "<14>Jan  1 00:00:00 actions app: Full regression test",
        "tags": {"component":"regression","path":"edge->mothership","channel":"ci"}
    }]
    
    print(f"✅ Test ID: {test_id}")
    
    # 5. Write events through sinks manager (like the server does)
    print("5️⃣ Writing events through SinksManager...")
    sink_results = await sinks_manager.write_events(events)
    print(f"📊 Sink results: {sink_results}")
    
    # 6. Validate results
    print("6️⃣ Validating results...")
    loki_result = sink_results.get("loki", {})
    
    if loki_result.get("written", 0) > 0:
        print(f"✅ SUCCESS: Loki received {loki_result['written']} events immediately!")
        print(f"   HTTP calls made: {mock_http_client.post.call_count}")
        if mock_http_client.post.call_count > 0:
            # Check the payload sent to Loki
            call_args = mock_http_client.post.call_args
            payload = call_args[1].get('json', {})
            streams = payload.get('streams', [])
            print(f"   Streams sent to Loki: {len(streams)}")
            if streams and streams[0].get('values'):
                log_line = streams[0]['values'][0][1]  # [timestamp, log_line]
                if test_id in log_line:
                    print(f"   ✅ Test ID found in Loki log: {test_id}")
                else:
                    print(f"   ❌ Test ID not found in log: {log_line}")
        success = True
    else:
        print(f"❌ FAILURE: Loki did not receive events")
        print(f"   Written: {loki_result.get('written', 0)}")
        print(f"   Queued: {loki_result.get('queued', 0)}")
        print(f"   Errors: {loki_result.get('errors', 0)}")
        success = False
    
    # Cleanup
    await sinks_manager.stop()
    
    return success


if __name__ == "__main__":
    success = asyncio.run(test_regression_scenario())
    if success:
        print("\n🎉 REGRESSION SCENARIO TEST PASSED!")
        print("The fix should resolve the pipeline failure.")
    else:
        print("\n❌ REGRESSION SCENARIO TEST FAILED!")
        sys.exit(1)