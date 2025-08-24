#!/usr/bin/env python3
"""Script to debug mothership startup and ingestion errors."""

import os
import sys
import asyncio
import traceback
from pathlib import Path

# Set environment variables as in regression test
os.environ["LOKI_ENABLED"] = "true" 
os.environ["LOKI_URL"] = "http://localhost:3100"
os.environ["TSDB_ENABLED"] = "true"
os.environ["TSDB_HOST"] = "localhost"
os.environ["TSDB_PORT"] = "5432"
os.environ["TSDB_DATABASE"] = "mothership"
os.environ["TSDB_USERNAME"] = "postgres"
os.environ["TSDB_PASSWORD"] = "postgres"
os.environ["MOTHERSHIP_DB_DSN"] = "postgresql://postgres:postgres@localhost:5432/mothership"

# Add mothership to path
sys.path.insert(0, str(Path(__file__).parent / "mothership"))

async def test_server_startup():
    """Test if the mothership server can start up without database."""
    try:
        print("Testing mothership imports...")
        from app.server import app
        from app.config import ConfigManager
        print("✅ Imports successful")
        
        # Test config loading
        print("\nTesting configuration...")
        config_manager = ConfigManager()
        config = config_manager.get_config()
        print(f"✅ Config loaded. Enabled sinks: {config_manager.get_enabled_sinks()}")
        
        # Test app state setup (without database)
        print("\nTesting app components initialization...")
        
        # Test pipeline
        from app.pipeline.processor import Pipeline
        from app.pipeline.processors_redaction import RedactionPipeline, PIISafetyValidator
        from app.pipeline.processors_enrich import (
            AddTagsProcessor,
            SeverityMapProcessor, 
            ServiceFromPathProcessor,
            GeoHintProcessor,
            SiteEnvTagsProcessor,
            TimestampNormalizer,
        )
        
        pipeline = Pipeline(config["pipeline"])
        processor_config = config["pipeline"]["processors"]

        # Add processors as in server.py
        if processor_config.get("redaction", {}).get("enabled", True):
            redaction_processor = RedactionPipeline(processor_config)
            pipeline.add_processor(redaction_processor)

            pii_validator = PIISafetyValidator({"strict_mode": False})
            pipeline.add_processor(pii_validator)

        if processor_config.get("enrichment", {}).get("enabled", True):
            enrich_config = processor_config["enrichment"]

            if enrich_config.get("add_tags"):
                add_tags_processor = AddTagsProcessor(enrich_config)
                pipeline.add_processor(add_tags_processor)

            severity_processor = SeverityMapProcessor(enrich_config)
            pipeline.add_processor(severity_processor)

            service_processor = ServiceFromPathProcessor({})
            pipeline.add_processor(service_processor)

            geo_processor = GeoHintProcessor({})
            pipeline.add_processor(geo_processor)

            site_processor = SiteEnvTagsProcessor({})
            pipeline.add_processor(site_processor)

            timestamp_processor = TimestampNormalizer({})
            pipeline.add_processor(timestamp_processor)
            
        print(f"✅ Pipeline created with {len(pipeline.processors)} processors")
        
        # Test sinks manager (without database)
        print("\nTesting sinks manager...")
        from app.storage.sinks import SinksManager
        
        try:
            sinks_manager = SinksManager(config, tsdb_writer=None)  # No database
            print(f"✅ SinksManager created with sinks: {list(sinks_manager.sinks.keys())}")
        except Exception as e:
            print(f"❌ SinksManager creation failed: {e}")
            traceback.print_exc()
            return False
            
        # Test event processing without database writes
        print("\nTesting event processing...")
        test_event = {
            "timestamp": "2025-01-01T00:00:00Z",
            "type": "syslog",
            "message": "Test message for debugging",
            "hostname": "test-host",
            "severity": "info"
        }
        
        try:
            processed_event = await pipeline.process_single_event(test_event)
            print(f"✅ Event processed successfully: {processed_event.get('message', 'N/A')[:50]}...")
        except Exception as e:
            print(f"❌ Event processing failed: {e}")
            traceback.print_exc()
            return False
            
        print("\n🎉 All components initialized successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Server startup test failed: {e}")
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = asyncio.run(test_server_startup())
    if success:
        print("\n✅ Mothership components can initialize successfully")
    else:
        print("\n❌ Mothership has initialization issues")
        sys.exit(1)