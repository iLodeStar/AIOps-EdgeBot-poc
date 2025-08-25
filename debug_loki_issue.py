#!/usr/bin/env python3
"""Debug script to reproduce the exact Loki issue from regression tests."""

import asyncio
import json
import os
import sys
from pathlib import Path

# Set environment variables exactly as in the regression test
os.environ["LOKI_ENABLED"] = "true"
os.environ["LOKI_URL"] = "http://localhost:3100"
os.environ["GITHUB_ACTIONS"] = "true"  # Simulate CI environment
os.environ["MOTHERSHIP_LOG_LEVEL"] = "INFO"  # For CI detection

# Add mothership to path
sys.path.insert(0, str(Path(__file__).parent / "mothership"))

async def debug_loki_issue():
    """Debug the exact Loki issue."""
    try:
        from app.storage.loki import LokiClient
        
        # Create test event exactly as used in the regression test
        test_event = {
            "timestamp": "2025-01-01T00:00:00Z",
            "type": "syslog",
            "message": "Full regression test via GitHub Actions regress-test-123",
            "hostname": "actions-runner",
            "severity": "info",
            "_internal": "should_be_dropped",
            "raw_message": "<14>Jan  1 00:00:00 actions app: Full regression test",
            "tags": {"component": "regression", "path": "edge->mothership", "channel": "ci"}
        }
        
        # Create Loki client with minimal config
        loki_config = {
            "enabled": True,
            "url": "http://localhost:3100",
            "batch_size": 10,
            "batch_timeout_seconds": 2.0
        }
        
        print("Creating Loki client...")
        loki_client = LokiClient(loki_config)
        
        print("Testing CI environment detection...")
        print(f"GITHUB_ACTIONS: {os.getenv('GITHUB_ACTIONS')}")
        print(f"PYTEST_CURRENT_TEST: {os.getenv('PYTEST_CURRENT_TEST')}")
        print(f"MOTHERSHIP_LOG_LEVEL: {os.getenv('MOTHERSHIP_LOG_LEVEL')}")
        print(f"_is_ci_environment(): {loki_client._is_ci_environment()}")
        
        # Test event conversion
        print("\nTesting event conversion...")
        loki_entry = loki_client._convert_to_loki_entry(test_event)
        if loki_entry:
            print(f"Successfully converted event to Loki entry:")
            print(f"  Timestamp: {loki_entry['timestamp']}")
            print(f"  Labels: {loki_entry['labels']}")
            print(f"  Line: {loki_entry['line']}")
        else:
            print("❌ Failed to convert event to Loki entry")
            return False
        
        print("\nTesting write_events without starting client...")
        result = await loki_client.write_events([test_event])
        print(f"Write result (no client): {result}")
        
        print("\nStarting Loki client...")
        await loki_client.start()
        
        print("Testing write_events with started client...")
        result = await loki_client.write_events([test_event])
        print(f"Write result (with client): {result}")
        
        # Wait a bit to see if batch flush happens
        print("Waiting 5 seconds for batch flush...")
        await asyncio.sleep(5)
        
        print("Stopping Loki client...")
        await loki_client.stop()
        
        print("✅ Debug completed successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Debug failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = asyncio.run(debug_loki_issue())
    if not success:
        sys.exit(1)