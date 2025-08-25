#!/usr/bin/env python3
"""
Debug the Loki regression test failure by simulating the exact data processing.

This script will help identify why the Loki query is returning empty results.
"""

import asyncio
import json
import sys
import time
from pathlib import Path

# Add mothership to path
sys.path.insert(0, str(Path(__file__).parent / "mothership"))

async def debug_loki_issue():
    """Debug what happens to the test data in the Loki processing pipeline."""
    
    print("🔍 Debugging Loki regression test failure...\n")
    
    # Simulate the exact test ID and payload from the workflow
    test_id = "regress-1234567890"  # Simulate test ID like workflow
    
    # This is the exact payload structure from the workflow (before jq modification)
    original_payload = {
        "messages": [
            {
                "timestamp": "2025-01-01T00:00:00Z",
                "type": "syslog",
                "message": "Full regression test via GitHub Actions",
                "hostname": "actions-runner", 
                "severity": "info",
                "_internal": "should_be_dropped",
                "raw_message": "<14>Jan  1 00:00:00 actions app: Full regression test",
                "tags": {"component":"regression","path":"edge->mothership","channel":"ci"}
            }
        ]
    }
    
    # Apply the jq modification: .messages[0].message += " TEST_ID" 
    payload_with_test_id = json.loads(json.dumps(original_payload))
    payload_with_test_id["messages"][0]["message"] += f" {test_id}"
    
    print(f"✅ Test ID: {test_id}")
    print(f"✅ Modified payload: {json.dumps(payload_with_test_id, indent=2)}")
    
    try:
        from app.storage.loki import LokiClient
        
        # Create LokiClient like in the regression environment
        loki_config = {
            "enabled": True,
            "url": "http://localhost:3100"
        }
        loki_client = LokiClient(loki_config)
        
        # Process the message like the mothership server would
        message_event = payload_with_test_id["messages"][0]
        
        print(f"\n🔄 Processing event through Loki conversion...")
        print(f"Raw event: {json.dumps(message_event, indent=2)}")
        
        # Convert to Loki entry
        loki_entry = loki_client._convert_to_loki_entry(message_event)
        
        if loki_entry:
            print(f"\n✅ Loki entry created:")
            print(f"  Labels: {loki_entry['labels']}")
            print(f"  Line: {loki_entry['line']}")
            print(f"  Timestamp: {loki_entry['timestamp']}")
            
            # Analyze the query compatibility
            print(f"\n🔍 Query Analysis:")
            
            # Check if source="mothership" matches
            source_label = loki_entry['labels'].get('source')
            print(f"  Source label: '{source_label}'")
            if source_label == 'mothership':
                print(f"  ✅ Would match query {{source=\"mothership\"}}")
            else:
                print(f"  ❌ Would NOT match query {{source=\"mothership\"}} (got '{source_label}')")
            
            # Check if the line contains the test_id
            line_content = loki_entry['line']
            print(f"  Line content: '{line_content}'")
            if test_id in line_content:
                print(f"  ✅ Line contains test_id '{test_id}'")
                print(f"  ✅ Would match query |= \"{test_id}\"")
            else:
                print(f"  ❌ Line does NOT contain test_id '{test_id}'")
                print(f"  ❌ Would NOT match query |= \"{test_id}\"")
            
            # Overall assessment
            matches_query = (source_label == 'mothership') and (test_id in line_content)
            print(f"\n🎯 Query Compatibility Assessment:")
            print(f"  Query: {{source=\"mothership\"}} |= \"{test_id}\"")
            if matches_query:
                print(f"  ✅ Event WOULD be found by this query")
            else:
                print(f"  ❌ Event would NOT be found by this query")
                
        else:
            print(f"\n❌ Failed to convert event to Loki entry")
            return False
            
    except ImportError as e:
        print(f"❌ Failed to import LokiClient: {e}")
        return False
    except Exception as e:
        print(f"❌ Error during processing: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    print(f"\n✅ Debug analysis completed!")
    return True

if __name__ == "__main__":
    success = asyncio.run(debug_loki_issue())
    if not success:
        sys.exit(1)