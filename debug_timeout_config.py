#!/usr/bin/env python3
"""
Debug test to check timeout configuration in CI environment.
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

# Set the EXACT environment variables used in CI regression test
os.environ["LOKI_ENABLED"] = "true"
os.environ["LOKI_URL"] = "http://localhost:3100"
os.environ["TSDB_ENABLED"] = "true"  
os.environ["TSDB_HOST"] = "localhost"
os.environ["TSDB_PORT"] = "5432"
os.environ["TSDB_DATABASE"] = "mothership"
os.environ["TSDB_USERNAME"] = "postgres"
os.environ["TSDB_PASSWORD"] = "postgres"
os.environ["MOTHERSHIP_DB_DSN"] = "postgresql://postgres:postgres@localhost:5432/mothership"
os.environ["MOTHERSHIP_LOG_LEVEL"] = "INFO"

# CI environment flags
os.environ["GITHUB_ACTIONS"] = "true"

# Add mothership to path
sys.path.insert(0, str(Path(__file__).parent / "mothership"))

async def debug_timeout_config():
    """Debug the timeout configuration."""
    
    print("🔍 Debugging timeout configuration...")
    
    try:
        from app.config import ConfigManager
        from app.storage.sinks import SinksManager
        
        # Initialize config
        config_manager = ConfigManager()
        config = config_manager._config
        print(f"🔍 Config enabled sinks: {config_manager.get_enabled_sinks()}")
        
        # Initialize sinks manager
        sinks_manager = SinksManager(config, tsdb_writer=None)
        
        # Check the actual configuration that was applied
        if 'loki' in sinks_manager.sinks:
            loki_resilient_sink = sinks_manager.sinks['loki']
            print(f"🔍 Loki sink retry config: {loki_resilient_sink.config.get('retry', {})}")
            print(f"🔍 Loki sink timeout: {loki_resilient_sink.config.get('retry', {}).get('timeout_ms', 'NOT SET')}ms")
            
            # Check the retry manager configuration
            if loki_resilient_sink.retry_manager:
                print(f"🔍 Retry manager timeout: {loki_resilient_sink.retry_manager.timeout_ms}ms")
            else:
                print("❌ No retry manager found")
        else:
            print("❌ No loki sink found")
            
    except Exception as e:
        print(f"❌ Debug failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(debug_timeout_config())