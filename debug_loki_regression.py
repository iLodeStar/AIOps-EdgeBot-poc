#!/usr/bin/env python3
"""Debug script to identify the root cause of Loki regression pipeline failure."""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

# Add mothership to path
sys.path.insert(0, str(Path(__file__).parent / "mothership"))

# Set environment variables like the regression pipeline
os.environ["LOKI_ENABLED"] = "true"
os.environ["LOKI_URL"] = "http://localhost:3100"
os.environ["TSDB_ENABLED"] = "false"  # Disable TSDB to focus on Loki
os.environ["MOTHERSHIP_LOG_LEVEL"] = "DEBUG"

from mothership.app.config import ConfigManager
from mothership.app.storage.loki import LokiClient
from mothership.app.storage.sinks import SinksManager


async def debug_loki_regression():
    """Debug the Loki regression test failure."""
    print("🔍 DEBUG: Loki Regression Pipeline Failure")
    print("=" * 50)
    
    print("\n1️⃣ Testing Configuration Loading...")
    config_manager = ConfigManager()
    config = config_manager.load_config()
    
    print(f"✅ Config loaded successfully")
    print(f"📋 Enabled sinks: {config_manager.get_enabled_sinks()}")
    print(f"📋 Loki config: {config.get('sinks', {}).get('loki', {})}")
    
    print("\n2️⃣ Testing Loki Client directly...")
    loki_config = config.get('sinks', {}).get('loki', {})
    if not loki_config.get('enabled', False):
        print("❌ Loki is NOT enabled in config")
        print(f"   Raw config: {loki_config}")
        print("   This is likely the root cause!")
        return False
    
    loki_client = LokiClient(loki_config)
    
    # Try to start the client without actually connecting to Loki
    print(f"✅ Loki client created with config: enabled={loki_config.get('enabled')}, url={loki_config.get('url')}")
    
    print("\n3️⃣ Testing Event Conversion...")
    # Create test event like the regression pipeline
    test_event = {
        "timestamp": "2025-01-01T00:00:00Z",
        "type": "syslog",
        "message": "Full regression test via GitHub Actions test-12345",
        "hostname": "actions-runner",
        "severity": "info",
        "_internal": "should_be_dropped",
        "raw_message": "<14>Jan  1 00:00:00 actions app: Full regression test",
        "tags": {"component":"regression","path":"edge->mothership","channel":"ci"}
    }
    
    # Convert to Loki entry
    loki_entry = loki_client._convert_to_loki_entry(test_event)
    if loki_entry:
        print(f"✅ Event converted successfully:")
        print(f"   Timestamp: {loki_entry['timestamp']}")
        print(f"   Labels: {loki_entry['labels']}")
        print(f"   Line: {loki_entry['line'][:100]}...")
    else:
        print("❌ Event conversion failed!")
        return False
    
    print("\n4️⃣ Testing SinksManager Integration...")
    # Test with no TSDB writer (like when TSDB is disabled)
    sinks_manager = SinksManager(config, tsdb_writer=None)
    
    print(f"📋 SinksManager sink names: {sinks_manager.get_sink_names()}")
    
    # Check if Loki sink is present
    loki_sink = sinks_manager.get_sink("loki")
    if not loki_sink:
        print("❌ Loki sink not found in SinksManager!")
        return False
    else:
        print("✅ Loki sink found in SinksManager")
        print(f"   Enabled: {loki_sink.is_enabled()}")
    
    print("\n5️⃣ Testing write_events simulation (without actual Loki)...")
    # Simulate the exact flow from the regression test
    test_events = [test_event]
    
    # This would normally fail without a real Loki server, but let's see the flow
    try:
        results = await loki_client.write_events(test_events)
        print(f"✅ write_events completed:")
        print(f"   Results: {results}")
        
        if results.get('queued', 0) > 0:
            print(f"   ✅ Event queued for batching: {results['queued']}")
        else:
            print(f"   ❌ No events queued: {results}")
            
    except Exception as e:
        print(f"❌ write_events failed: {e}")
        return False
    
    print("\n🎯 SUMMARY:")
    if loki_config.get('enabled', False):
        print("✅ Loki is properly enabled in configuration")
        print("✅ Event conversion works correctly") 
        print("✅ SinksManager contains Loki sink")
        print("💡 Root cause is likely:")
        print("   - Network connectivity between mothership and Loki in CI")
        print("   - Timing issue (batching delay vs immediate query)")
        print("   - Loki service not ready when mothership starts")
    else:
        print("❌ Loki is NOT enabled - this is the root cause!")
        
    return True


if __name__ == "__main__":
    success = asyncio.run(debug_loki_regression())
    if success:
        print("\n✅ DEBUG COMPLETE")
    else:
        print("\n❌ DEBUG FAILED")
        sys.exit(1)