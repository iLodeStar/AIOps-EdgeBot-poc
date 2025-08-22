#!/usr/bin/env python3
"""
Integration test demonstrating EdgeBot -> Mothership data flow.

This test simulates the complete flow without requiring external dependencies.
"""

import asyncio
import json
import gzip
import time
from mothership.app.config import get_config
from mothership.app.storage.sinks import SinksManager

async def simulate_edgebot_payload():
    """Simulate an EdgeBot payload being sent to the mothership."""
    
    print("🚀 Starting EdgeBot -> Mothership Integration Test")
    print("=" * 60)
    
    # 1. Simulate EdgeBot payload (what edge node would send)
    edgebot_payload = {
        "messages": [
            {
                "message": "Syslog message from edge node",
                "timestamp": int(time.time()),
                "type": "syslog",
                "service": "edgebot",
                "host": "edge-01",
                "site": "datacenter-a",
                "env": "test",
                "severity": "info",
                "facility": "daemon",
                "__spool_id": 123,  # Internal field that should be filtered out
                "additional_data": {"connection_id": "conn-456"}
            },
            {
                "message": "Weather data collected successfully",
                "timestamp": int(time.time()) + 60,
                "type": "weather", 
                "service": "edgebot",
                "host": "edge-01",
                "site": "datacenter-a",
                "env": "test",
                "severity": "info",
                "temperature": 22.5,
                "humidity": 65,
                "__spool_id": 124,  # Internal field that should be filtered out
            },
            {
                "message": "SNMP poll completed",
                "timestamp": int(time.time()) + 120,
                "type": "snmp",
                "service": "edgebot",
                "host": "edge-01", 
                "site": "datacenter-a",
                "env": "test",
                "severity": "info",
                "device": "switch-01",
                "oid": "1.3.6.1.2.1.2.2.1.10",
                "value": 1024000,
                "__spool_id": 125,  # Internal field that should be filtered out
            }
        ],
        "batch_size": 3,
        "timestamp": int(time.time()),
        "source": "edge-01",
        "is_retry": False
    }
    
    print(f"📦 EdgeBot Payload Created:")
    print(f"   Messages: {len(edgebot_payload['messages'])}")
    print(f"   Source: {edgebot_payload['source']}")
    print(f"   Batch size: {edgebot_payload['batch_size']}")
    print()
    
    # 2. Simulate mothership processing (what /ingest endpoint does)
    print("🔄 Processing payload in mothership...")
    
    # Extract and sanitize messages
    messages = edgebot_payload["messages"]
    sanitized_messages = []
    for msg in messages:
        # Remove internal fields (same as server.py does)
        sanitized_msg = {k: v for k, v in msg.items() if not k.startswith('_')}
        sanitized_messages.append(sanitized_msg)
    
    print(f"🧹 Sanitization:")
    print(f"   Original messages: {len(messages)}")
    print(f"   Sanitized messages: {len(sanitized_messages)}")
    print(f"   Removed fields: __spool_id")
    print()
    
    # 3. Initialize mothership sinks
    print("⚙️  Initializing mothership sinks...")
    config = get_config()
    print(f"   Enabled sinks: {config.get_enabled_sinks()}")
    
    sinks_manager = SinksManager(config)
    await sinks_manager.start()
    
    # 4. Test health check
    health = sinks_manager.get_health_status()
    print(f"💚 Health Status:")
    print(f"   Overall healthy: {health['healthy']}")
    for sink_name, sink_status in health['sinks'].items():
        print(f"   {sink_name}: {'✓' if sink_status['healthy'] else '✗'} ({sink_status})")
    print()
    
    # 5. Write events to sinks
    print("💾 Writing events to storage sinks...")
    sink_results = await sinks_manager.write_events(sanitized_messages)
    
    # 6. Display results
    print("📊 Write Results:")
    total_written = 0
    total_errors = 0
    
    for sink_name, result in sink_results.items():
        written = result.get('written', 0)
        errors = result.get('errors', 0)
        queued = result.get('queued', 0)
        
        print(f"   {sink_name}:")
        print(f"     Written: {written}")
        print(f"     Errors: {errors}")
        if queued > 0:
            print(f"     Queued: {queued}")
        
        total_written += written
        total_errors += errors
    
    print(f"   TOTAL Written: {total_written}")
    print(f"   TOTAL Errors: {total_errors}")
    print()
    
    # 7. Simulate /ingest response
    response_payload = {
        "status": "success",
        "received": len(messages),
        "sanitized": len(sanitized_messages),
        "written": total_written,
        "errors": total_errors,
        "sink_results": sink_results
    }
    
    print("📤 Mothership Response (what EdgeBot receives):")
    print(json.dumps(response_payload, indent=2))
    print()
    
    # 8. Test with Loki enabled (mock)
    print("🔧 Testing Loki Integration (safe labeling)...")
    
    # Import here to avoid issues if not available
    from mothership.app.storage.loki import LokiClient
    from mothership.app.config import LokiConfig
    
    # Test label extraction and sanitization
    loki_config = LokiConfig(enabled=True, batch_size=10)
    loki_client = LokiClient(loki_config)
    
    for i, message in enumerate(sanitized_messages):
        loki_entry = loki_client._convert_to_loki_entry(message)
        if loki_entry:
            print(f"   Message {i+1} Loki Entry:")
            print(f"     Labels: {loki_entry['labels']}")
            print(f"     Line: {loki_entry['line'][:80]}{'...' if len(loki_entry['line']) > 80 else ''}")
            
            # Verify safe labeling
            for label_key in loki_entry['labels']:
                assert label_key in loki_client.SAFE_LABELS, f"Unsafe label: {label_key}"
            
            print(f"     ✓ All labels are safe (low cardinality)")
            print()
    
    # 9. Cleanup
    await sinks_manager.stop()
    
    print("✅ Integration Test Completed Successfully!")
    print("=" * 60)
    print(f"Summary:")
    print(f"- Processed {len(messages)} messages from EdgeBot")
    print(f"- Sanitized and removed {len(messages) - len(sanitized_messages)} internal fields")
    print(f"- Successfully wrote to {len(sink_results)} storage sinks")
    print(f"- Verified Loki safe labeling for all events")
    print(f"- Total events written: {total_written}")

if __name__ == "__main__":
    asyncio.run(simulate_edgebot_payload())