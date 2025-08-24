#!/usr/bin/env python3
"""Test ingestion with Loki only (no TSDB)."""

import asyncio
import json
import os
import sys
import traceback
from pathlib import Path

# Set environment variables to disable TSDB and enable only Loki  
os.environ["LOKI_ENABLED"] = "true"
os.environ["LOKI_URL"] = "http://localhost:3100"
os.environ["TSDB_ENABLED"] = "false"  # Disable TSDB to test theory

# Add mothership to path
sys.path.insert(0, str(Path(__file__).parent / "mothership"))

async def test_loki_only_ingestion():
    """Test ingestion with only Loki sink enabled."""
    
    print("🔍 Testing ingestion with Loki only (TSDB disabled)...\n")
    
    # Same test payload
    test_id = "regress-1234567890"
    
    payload = {
        "messages": [
            {
                "timestamp": "2025-01-01T00:00:00Z",
                "type": "syslog", 
                "message": f"Full regression test via GitHub Actions {test_id}",
                "hostname": "actions-runner", 
                "severity": "info",
                "_internal": "should_be_dropped",
                "raw_message": "<14>Jan  1 00:00:00 actions app: Full regression test",
                "tags": {"component":"regression","path":"edge->mothership","channel":"ci"}
            }
        ]
    }
    
    try:
        # Import required modules
        from app.server import IngestRequest
        from app.config import ConfigManager
        from app.pipeline.processor import Pipeline
        from app.storage.sinks import SinksManager
        from app.pipeline.processors_redaction import RedactionPipeline, PIISafetyValidator
        from app.pipeline.processors_enrich import (
            AddTagsProcessor, SeverityMapProcessor, ServiceFromPathProcessor, 
            GeoHintProcessor, SiteEnvTagsProcessor, TimestampNormalizer,
        )
        
        # Load config
        print("Loading configuration...")
        config_manager = ConfigManager()
        config = config_manager.get_config()
        print(f"Config loaded. Enabled sinks: {config_manager.get_enabled_sinks()}")
        
        # Make sure TSDB is disabled
        config['sinks']['timescaledb']['enabled'] = False
        print(f"Modified config - TSDB enabled: {config['sinks']['timescaledb']['enabled']}")
        
        # Create pipeline
        pipeline = Pipeline(config["pipeline"])
        processor_config = config["pipeline"]["processors"]

        # Add processors
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
            
        print(f"Pipeline created with {len(pipeline.processors)} processors")
        
        # Create sinks manager without TSDB
        sinks_manager = SinksManager(config, tsdb_writer=None)
        print(f"SinksManager created with sinks: {list(sinks_manager.sinks.keys())}")
        
        await sinks_manager.start()
        print("SinksManager started")
        
        # Process ingestion
        request = IngestRequest(**payload)
        events = request.messages
        
        processed_events = []
        for event in events:
            event_dict = event.model_dump()
            processed_event = await pipeline.process_single_event(event_dict)
            processed_events.append(processed_event)
                
        print(f"Processed {len(processed_events)} events")

        # Write to sinks (should be much faster without TSDB)
        import time
        start_time = time.time()
        sink_results = await sinks_manager.write_events(processed_events)
        end_time = time.time()
        
        print(f"Sink write completed in {end_time - start_time:.2f} seconds")
        print(f"Sink write results: {sink_results}")
        
        # Check labels
        if processed_events:
            from app.storage.loki import LokiClient
            loki_client = LokiClient({"enabled": True, "url": "http://localhost:3100"})
            labels = loki_client._extract_safe_labels(processed_events[0])
            print(f"Labels for Loki: {labels}")
            
            # Check if source=mothership
            if labels.get('source') == 'mothership':
                print("✅ Labels would match query {source=\"mothership\"}")
                
                # Check if message contains test_id
                if test_id in processed_events[0].get('message', ''):
                    print(f"✅ Message contains test_id: {test_id}")
                else:
                    print(f"❌ Message does NOT contain test_id: {test_id}")
                    print(f"Message: {processed_events[0].get('message', '')}")
            else:
                print(f"❌ Source label is '{labels.get('source')}', not 'mothership'")
                
        await sinks_manager.stop()
        
        print("\n🎉 Loki-only ingestion test completed successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Loki-only ingestion test failed: {e}")
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = asyncio.run(test_loki_only_ingestion())
    if not success:
        sys.exit(1)