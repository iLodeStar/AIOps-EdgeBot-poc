#!/usr/bin/env python3
"""Test the actual flushing mechanism for Loki CI fix."""

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock

# Add mothership to path
sys.path.insert(0, str(Path(__file__).parent / "mothership"))

# Set CI environment variables
os.environ["LOKI_ENABLED"] = "true" 
os.environ["LOKI_URL"] = "http://localhost:3100"
os.environ["GITHUB_ACTIONS"] = "true"  # Simulate CI environment

from mothership.app.storage.loki import LokiClient


async def test_flush_mechanism():
    """Test that the flush mechanism works properly in CI."""
    print("🔧 Testing Loki Flush Mechanism in CI")
    print("=" * 45)
    
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
    
    # Mock the HTTP client to simulate successful Loki responses
    mock_response = Mock()
    mock_response.status_code = 204  # Loki success response
    
    mock_http_client = AsyncMock()
    mock_http_client.post.return_value = mock_response
    
    # Start the client to initialize the HTTP client
    await client.start()
    
    # Replace the real HTTP client with our mock
    client.client = mock_http_client
    
    print(f"✅ CI environment detected: {client._is_ci_environment()}")
    print(f"✅ Mock HTTP client configured")
    
    # Test single event - should trigger immediate flush in CI
    test_event = {
        "timestamp": "2025-01-01T00:00:00Z",
        "type": "syslog",
        "message": "Test flush mechanism test-12345",
        "severity": "info", 
        "source": "mothership"
    }
    
    print(f"\n📤 Sending single event to trigger CI flush...")
    
    # Clear the batch queue first
    client._batch_queue.clear()
    
    result = await client.write_events([test_event])
    
    print(f"📊 Write result: {result}")
    print(f"📏 Batch queue size after write: {len(client._batch_queue)}")
    print(f"🌐 HTTP client post calls: {mock_http_client.post.call_count}")
    
    if mock_http_client.post.call_count > 0:
        print(f"✅ SUCCESS: HTTP POST was called - flush triggered!")
        call_args = mock_http_client.post.call_args
        print(f"   URL: {call_args[1].get('json', {}).get('url', 'N/A')}")
        payload = call_args[1].get('json', {})
        streams = payload.get('streams', [])
        print(f"   Streams sent: {len(streams)}")
        if streams:
            print(f"   First stream labels: {streams[0].get('stream', {})}")
    else:
        print(f"❌ FAILURE: No HTTP POST called - flush not triggered")
        return False
    
    if result.get('written', 0) > 0:
        print(f"✅ SUCCESS: Event marked as written: {result['written']}")
    else:
        print(f"⚠️  Event not marked as written (queued: {result.get('queued', 0)})")
    
    # Clean up
    await client.stop()
    
    return True


if __name__ == "__main__":
    success = asyncio.run(test_flush_mechanism())
    if success:
        print("\n✅ FLUSH MECHANISM TEST PASSED")
    else:
        print("\n❌ FLUSH MECHANISM TEST FAILED")
        sys.exit(1)