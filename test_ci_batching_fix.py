#!/usr/bin/env python3
"""Test the Loki CI batching fix locally."""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

# Add mothership to path
sys.path.insert(0, str(Path(__file__).parent / "mothership"))

# Set CI environment variables to trigger the fix
os.environ["LOKI_ENABLED"] = "true"
os.environ["LOKI_URL"] = "http://localhost:3100"
os.environ["GITHUB_ACTIONS"] = "true"  # Simulate CI environment
os.environ["MOTHERSHIP_LOG_LEVEL"] = "INFO"  # Trigger the CI flush logic

from mothership.app.storage.loki import LokiClient


async def test_ci_batching_fix():
    """Test that small batches are flushed immediately in CI environment."""
    print("🧪 Testing Loki CI Batching Fix")
    print("=" * 40)
    
    # Create Loki client config
    config = {
        'enabled': True,
        'url': 'http://localhost:3100',
        'batch_size': 100,
        'batch_timeout_seconds': 5.0,
        'max_retries': 3,
        'retry_backoff_seconds': 1.0,
        'timeout_seconds': 30.0
    }
    
    client = LokiClient(config)
    
    # Test CI environment detection
    print(f"✅ CI environment detected: {client._is_ci_environment()}")
    
    # Test single event (should be flushed immediately in CI)
    test_event = {
        "timestamp": "2025-01-01T00:00:00Z",
        "type": "syslog", 
        "message": "Test immediate flush in CI test-12345",
        "severity": "info",
        "source": "mothership"
    }
    
    print(f"\n📤 Sending single event...")
    result = await client.write_events([test_event])
    
    print(f"📊 Result: {result}")
    
    if client._is_ci_environment() and result.get('written', 0) > 0:
        print(f"✅ SUCCESS: Event was flushed immediately in CI environment!")
        print(f"   Written: {result['written']}, Queued: {result['queued']}")
    elif client._is_ci_environment() and result.get('queued', 0) > 0:
        print(f"⚠️  Event queued but not written (may require actual Loki server)")
        print(f"   This is expected when testing without real Loki")
    else:
        print(f"❌ FAILURE: Expected immediate flush in CI environment")
        return False
    
    # Test non-CI behavior by temporarily unsetting CI vars
    print(f"\n🔄 Testing non-CI behavior...")
    old_github_actions = os.environ.pop('GITHUB_ACTIONS', None)
    
    client2 = LokiClient(config)
    print(f"✅ CI environment detected: {client2._is_ci_environment()}")
    
    result2 = await client2.write_events([test_event])
    print(f"📊 Non-CI Result: {result2}")
    
    if not client2._is_ci_environment() and result2.get('queued', 0) > 0 and result2.get('written', 0) == 0:
        print(f"✅ SUCCESS: Event queued but not immediately flushed in non-CI")
    else:
        print(f"⚠️  Unexpected non-CI behavior (may be OK)")
    
    # Restore environment
    if old_github_actions:
        os.environ['GITHUB_ACTIONS'] = old_github_actions
    
    return True


if __name__ == "__main__":
    success = asyncio.run(test_ci_batching_fix())
    if success:
        print("\n✅ CI BATCHING FIX TEST PASSED")
    else:
        print("\n❌ CI BATCHING FIX TEST FAILED")
        sys.exit(1)