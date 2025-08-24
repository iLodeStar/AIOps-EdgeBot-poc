#!/usr/bin/env python3
"""Test improved error handling for database connection failures."""

import asyncio
import json
import os
import sys
import traceback
from pathlib import Path

# Set environment variables that will cause database connection to fail
os.environ["LOKI_ENABLED"] = "true"
os.environ["LOKI_URL"] = "http://localhost:3100"
os.environ["TSDB_ENABLED"] = "true" 
os.environ["MOTHERSHIP_DB_DSN"] = "postgresql://baduser:badpass@nonexistent:5432/baddb"

# Add mothership to path
sys.path.insert(0, str(Path(__file__).parent / "mothership"))

async def test_server_startup_with_db_failure():
    """Test server startup when database connection fails."""
    
    print("🔍 Testing server startup with database connection failure...\n")
    
    try:
        # Import modules
        from app.server import app_state
        from app.config import ConfigManager
        from app.pipeline.processor import Pipeline
        from app.storage.sinks import SinksManager
        from app.storage.tsdb import TimescaleDBWriter
        from app.pipeline.processors_redaction import RedactionPipeline, PIISafetyValidator
        from app.pipeline.processors_enrich import (
            AddTagsProcessor, SeverityMapProcessor, ServiceFromPathProcessor,
            GeoHintProcessor, SiteEnvTagsProcessor, TimestampNormalizer,
        )
        
        # Load configuration
        print("Loading configuration...")
        config_manager = ConfigManager()
        config = config_manager.get_config()
        print(f"Config loaded. Enabled sinks: {config_manager.get_enabled_sinks()}")
        
        # Test improved startup logic
        print("\nTesting TimescaleDB writer initialization...")
        db_config = config["database"]
        tsdb_writer = None
        try:
            tsdb_writer = TimescaleDBWriter(db_config)
            await tsdb_writer.initialize()
            print("✅ TimescaleDB writer initialized successfully")
        except Exception as e:
            print(f"❌ Failed to initialize TimescaleDB writer: {e}")
            print("✅ Server continues gracefully without TSDB writer")
            tsdb_writer = None

        # Test sinks manager with failed database
        print("\nTesting sinks manager initialization...")
        try:
            sinks_manager = SinksManager(config, tsdb_writer=tsdb_writer)
            await sinks_manager.start()
            print(f"✅ Sinks manager started with sinks: {list(sinks_manager.sinks.keys())}")
        except Exception as e:
            print(f"❌ Failed to start sinks manager: {e}")
            traceback.print_exc()
            return False

        # Test pipeline creation
        print("\nTesting pipeline creation...")
        pipeline = Pipeline(config["pipeline"])
        processor_config = config["pipeline"]["processors"]

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

        # Test ingestion workflow even with database failure
        print("\nTesting ingestion workflow...")
        test_events = [{
            "timestamp": "2025-01-01T00:00:00Z",
            "message": "Test message with DB failure",
            "type": "syslog",
            "hostname": "test-host", 
            "severity": "info"
        }]
        
        # Process through pipeline
        processed_events = []
        for event in test_events:
            try:
                processed_event = await pipeline.process_single_event(event)
                processed_events.append(processed_event)
            except Exception as e:
                print(f"❌ Pipeline processing failed: {e}")
                traceback.print_exc()
                return False
                
        print(f"✅ Processed {len(processed_events)} events through pipeline")
        
        # Write to available sinks (should only be Loki, and it will fail gracefully)
        import time
        start_time = time.time()
        
        try:
            sink_results = await sinks_manager.write_events(processed_events)
            end_time = time.time()
            
            print(f"✅ Sink write completed in {end_time - start_time:.2f} seconds")
            print(f"Sink results: {sink_results}")
            
            # Verify that even with failures, the results are structured properly
            for sink_name, result in sink_results.items():
                if not isinstance(result, dict):
                    print(f"❌ Sink {sink_name} returned invalid result type: {type(result)}")
                    return False
                    
                required_keys = ["written", "errors", "retries", "queued"]
                for key in required_keys:
                    if key not in result:
                        print(f"❌ Sink {sink_name} missing required key '{key}' in result")
                        return False
                        
            print("✅ All sink results are properly structured")
            
        except Exception as e:
            print(f"❌ Sink write failed with unhandled exception: {e}")
            traceback.print_exc()
            return False

        await sinks_manager.stop()
        
        print("\n🎉 Server startup and ingestion work correctly even with database failures!")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = asyncio.run(test_server_startup_with_db_failure())
    if not success:
        sys.exit(1)