#!/usr/bin/env python3
"""Direct test of Loki client to debug CI regression failure."""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

# Add mothership to path
sys.path.insert(0, str(Path(__file__).parent / "mothership"))


async def test_loki_direct():
    """Test Loki client directly to understand the CI failure."""
    print("🔍 Testing Loki client directly...")
    
    # Set CI environment variables exactly like in CI
    os.environ['GITHUB_ACTIONS'] = 'true'
    os.environ['MOTHERSHIP_LOG_LEVEL'] = 'INFO'
    os.environ['LOKI_ENABLED'] = 'true'
    os.environ['LOKI_URL'] = 'http://localhost:3100'
    
    test_id = f"regress-{int(time.time())}"
    print(f"Test ID: {test_id}")
    
    try:
        from app.storage.loki import LokiClient
        
        # Create Loki client with CI config
        config = {
            'enabled': True,
            'url': 'http://localhost:3100',
            'batch_size': 10,
            'batch_timeout_seconds': 2.0,
            'max_retries': 2
        }
        
        loki_client = LokiClient(config)
        print(f"CI environment detected: {loki_client._is_ci_environment()}")
        
        # Create a test event like the CI would process
        test_event = {
            "timestamp": "2025-01-01T00:00:00Z",
            "type": "syslog", 
            "message": f"Full regression test via GitHub Actions {test_id}",
            "hostname": "actions-runner",
            "severity": "info",
            "service": "actions-runner",  # This might be added by processors
            "source": "mothership"  # This should be added by default
        }
        
        print(f"Test event: {json.dumps(test_event, indent=2)}")
        
        # Test label extraction
        labels = loki_client._extract_safe_labels(test_event)
        print(f"Extracted labels: {labels}")
        
        # Test Loki entry conversion
        loki_entry = loki_client._convert_to_loki_entry(test_event)
        print(f"Loki entry: {loki_entry}")
        
        # Check if query pattern would match
        if loki_entry:
            source_matches = labels.get('source') == 'mothership'
            message_matches = test_id in loki_entry.get('line', '')
            
            print(f"\nQuery pattern analysis:")
            print(f"  source='mothership': {source_matches} (actual: '{labels.get('source')}')")
            print(f"  contains '{test_id}': {message_matches}")
            print(f"  Expected query: {{source=\"mothership\"}} |= \"{test_id}\"")
            
            if source_matches and message_matches:
                print("✅ Query pattern would match the event")
            else:
                print("❌ Query pattern would NOT match the event")
                return False
        else:
            print("❌ Failed to convert event to Loki entry")
            return False
        
        # Test the actual write
        print(f"\n🔄 Starting Loki client...")
        await loki_client.start()
        
        print(f"🔄 Writing event to Loki...")
        start_time = time.time()
        result = await loki_client.write_events([test_event])
        write_time = time.time() - start_time
        
        print(f"Write completed in {write_time:.3f}s")
        print(f"Write result: {result}")
        
        # Analyze the result
        written = result.get('written', 0)
        errors = result.get('errors', 0)
        queued = result.get('queued', 0)
        
        print(f"\nResult analysis:")
        print(f"  Written: {written}")
        print(f"  Errors: {errors}")
        print(f"  Queued: {queued}")
        
        if written > 0 and errors == 0:
            print("✅ Loki write succeeded")
            success = True
        elif written == 0 and errors > 0:
            print("❌ Loki write failed completely")
            success = False
        else:
            print(f"⚠️  Loki write partial result")
            success = written > 0
        
        print(f"\n🔄 Stopping Loki client...")
        await loki_client.stop()
        
        return success, test_id
        
    except Exception as e:
        print(f"❌ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        return False, test_id


if __name__ == "__main__":
    result = asyncio.run(test_loki_direct())
    print(f"\nFinal result: {result}")