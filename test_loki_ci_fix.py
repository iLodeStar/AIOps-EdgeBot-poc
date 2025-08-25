#!/usr/bin/env python3
"""Test to verify the Loki CI environment detection and timeout fix."""

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

# Add mothership to path
sys.path.insert(0, str(Path(__file__).parent / "mothership"))

async def test_ci_detection_current():
    """Test CI detection with current environment."""
    print("🔍 Testing current CI environment detection...")
    
    from app.storage.loki import LokiClient
    
    # Current environment detection
    config = {"enabled": True, "url": "http://localhost:3100"}
    client = LokiClient(config)
    
    print(f"GITHUB_ACTIONS={os.getenv('GITHUB_ACTIONS')}")
    print(f"MOTHERSHIP_LOG_LEVEL={os.getenv('MOTHERSHIP_LOG_LEVEL')}")
    print(f"PYTEST_CURRENT_TEST={os.getenv('PYTEST_CURRENT_TEST')}")
    print(f"LOKI_ENABLED={os.getenv('LOKI_ENABLED')}")
    
    is_ci = client._is_ci_environment()
    print(f"Current CI detection result: {is_ci}")
    
    if not is_ci:
        print("❌ CI detection failed with current environment")
        return False
    
    print("✅ CI detection working with current environment")
    return True

async def test_ci_detection_with_mothership_vars():
    """Test CI detection with mothership environment variables set."""
    print("\n🔍 Testing CI environment detection with mothership env vars...")
    
    with patch.dict(os.environ, {
        'GITHUB_ACTIONS': 'true',
        'MOTHERSHIP_LOG_LEVEL': 'INFO', 
        'LOKI_ENABLED': 'true'
    }):
        from app.storage.loki import LokiClient
        
        config = {"enabled": True, "url": "http://localhost:3100"}
        client = LokiClient(config)
        
        print(f"GITHUB_ACTIONS={os.getenv('GITHUB_ACTIONS')}")
        print(f"MOTHERSHIP_LOG_LEVEL={os.getenv('MOTHERSHIP_LOG_LEVEL')}")
        print(f"PYTEST_CURRENT_TEST={os.getenv('PYTEST_CURRENT_TEST')}")
        print(f"LOKI_ENABLED={os.getenv('LOKI_ENABLED')}")
        
        is_ci = client._is_ci_environment()
        print(f"CI detection result: {is_ci}")
        
        if not is_ci:
            print("❌ CI detection failed with mothership environment")
            return False
        
        print("✅ CI detection working with mothership environment")
        
        # Also test sinks manager CI detection
        from app.storage.sinks import SinksManager
        
        config = {
            "sinks": {
                "loki": {"enabled": True}
            },
            "sink_defaults": {}
        }
        
        manager = SinksManager(config, tsdb_writer=None)
        
        # Get the merged config that should have CI timeouts
        if 'loki' in manager.sinks:
            loki_sink = manager.sinks['loki']
            print(f"Loki sink config timeout: {getattr(loki_sink, 'config', {}).get('retry', {}).get('timeout_ms', 'not set')}")
        
        return True

async def test_timeout_values():
    """Test that timeouts are set correctly for CI environments."""
    print("\n🔍 Testing timeout values for CI environments...")
    
    # Test with CI environment variables
    with patch.dict(os.environ, {
        'GITHUB_ACTIONS': 'true',
        'MOTHERSHIP_LOG_LEVEL': 'INFO', 
        'LOKI_ENABLED': 'true'
    }):
        from app.storage.sinks import SinksManager
        
        config = {
            "sinks": {
                "loki": {"enabled": True, "url": "http://localhost:3100"}
            },
            "sink_defaults": {}
        }
        
        manager = SinksManager(config, tsdb_writer=None)
        
        if 'loki' in manager.sinks:
            loki_sink = manager.sinks['loki']
            timeout_ms = loki_sink.config.get('retry', {}).get('timeout_ms')
            print(f"Loki sink timeout in CI: {timeout_ms}ms")
            
            if timeout_ms >= 20000:  # Should be 20s or more for CI
                print("✅ CI timeout values are appropriate")
                return True
            else:
                print(f"❌ CI timeout too low: {timeout_ms}ms (should be >= 20000ms)")
                return False
        else:
            print("❌ Loki sink not found")
            return False

async def test_event_processing():
    """Test event processing and label extraction."""
    print("\n🔍 Testing event processing and label extraction...")
    
    with patch.dict(os.environ, {
        'GITHUB_ACTIONS': 'true',
        'MOTHERSHIP_LOG_LEVEL': 'INFO', 
        'LOKI_ENABLED': 'true'
    }):
        from app.storage.loki import LokiClient
        
        config = {"enabled": True, "url": "http://localhost:3100"}
        client = LokiClient(config)
        
        # Test event that matches the CI regression payload
        test_id = "regress-test-123"
        event = {
            "timestamp": "2025-01-01T00:00:00Z",
            "type": "syslog",
            "message": f"Full regression test via GitHub Actions {test_id}",
            "hostname": "actions-runner",
            "severity": "info",
            "_internal": "should_be_dropped",
            "raw_message": "<14>Jan  1 00:00:00 actions app: Full regression test",
            "tags": {"component":"regression","path":"edge->mothership","channel":"ci"}
        }
        
        # Convert to Loki entry
        loki_entry = client._convert_to_loki_entry(event)
        
        if not loki_entry:
            print("❌ Failed to convert event to Loki entry")
            return False
        
        print(f"Loki entry labels: {loki_entry['labels']}")
        print(f"Loki entry line: {loki_entry['line']}")
        
        # Check labels
        labels = loki_entry['labels']
        if labels.get('source') != 'mothership':
            print(f"❌ Source label wrong: {labels.get('source')} != 'mothership'")
            return False
        
        # Check if test_id is in the line
        if test_id not in loki_entry['line']:
            print(f"❌ Test ID not found in line: {loki_entry['line']}")
            return False
        
        print("✅ Event processing and label extraction working correctly")
        print(f"✅ Query {labels.get('source')} |= '{test_id}' would match this entry")
        
        return True

async def main():
    """Run all tests."""
    print("🚀 Testing Loki CI environment detection and configuration...\n")
    
    success = True
    
    # Test 1: Current environment CI detection
    if not await test_ci_detection_current():
        success = False
    
    # Test 2: CI detection with mothership variables
    if not await test_ci_detection_with_mothership_vars():
        success = False
    
    # Test 3: Timeout values
    if not await test_timeout_values():
        success = False
    
    # Test 4: Event processing
    if not await test_event_processing():
        success = False
    
    if success:
        print("\n🎉 All tests passed!")
        return True
    else:
        print("\n❌ Some tests failed")
        return False

if __name__ == "__main__":
    success = asyncio.run(main())
    if not success:
        sys.exit(1)