#!/usr/bin/env python3
"""Test the exact ingestion payload from the regression test."""

import asyncio
import json
import os
import sys
import traceback
from pathlib import Path

# Set environment variables exactly as in the regression test
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

async def test_exact_ingestion_payload():
    """Test the exact payload from the regression test."""
    
    print("🔍 Testing exact ingestion payload from regression test...\n")
    
    # This is the exact payload structure from the regression workflow
    test_id = "regress-1234567890"  # Simulate test ID
    
    payload = {
        "messages": [
            {
                "timestamp": "2025-01-01T00:00:00Z",
                "type": "syslog",
                "message": f"Full regression test via GitHub Actions {test_id}",
                "hostname": "actions-runner",
                "severity": "info",
                "_internal": "should_be_dropped",  # This should be dropped by redaction
                "raw_message": "<14>Jan  1 00:00:00 actions app: Full regression test",
                "tags": {"component":"regression","path":"edge->mothership","channel":"ci"}
            }
        ]
    }
    
    print(f"Test payload: {json.dumps(payload, indent=2)}")
    
    try:
        # Import server components
        from app.server import IngestRequest, IngestResponse
        from app.config import ConfigManager
        from app.pipeline.processor import Pipeline
        from app.storage.sinks import SinksManager
        from app.pipeline.processors_redaction import RedactionPipeline, PIISafetyValidator
        from app.pipeline.processors_enrich import (
            AddTagsProcessor,
            SeverityMapProcessor,
            ServiceFromPathProcessor, 
            GeoHintProcessor,
            SiteEnvTagsProcessor,
            TimestampNormalizer,
        )
        
        # Load configuration
        print("Loading configuration...")
        config_manager = ConfigManager()
        config = config_manager.get_config()
        print(f"Config loaded. Enabled sinks: {config_manager.get_enabled_sinks()}")
        
        # Create pipeline exactly as in server.py
        print("Creating pipeline...")
        pipeline = Pipeline(config["pipeline"])
        processor_config = config["pipeline"]["processors"]

        # Redaction processors
        if processor_config.get("redaction", {}).get("enabled", True):
            redaction_processor = RedactionPipeline(processor_config)
            pipeline.add_processor(redaction_processor)

            pii_validator = PIISafetyValidator({"strict_mode": False})
            pipeline.add_processor(pii_validator)

        # Enrichment processors  
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
        
        # Create sinks manager (without database connection for now)
        print("Creating sinks manager...")
        sinks_manager = SinksManager(config, tsdb_writer=None)
        print(f"SinksManager created with sinks: {list(sinks_manager.sinks.keys())}")
        
        await sinks_manager.start()
        print("SinksManager started")
        
        # Test the exact ingestion logic from server.py
        print("\nProcessing events through pipeline...")
        
        # Parse the request (simulate Pydantic validation)
        request = IngestRequest(**payload)
        events = request.messages
        
        print(f"Processing {len(events)} events")
        
        # Process events through pipeline
        processed_events = []
        for event in events:
            try:
                # Convert to dict for pipeline processing
                event_dict = event.model_dump()
                print(f"Processing event: {json.dumps(event_dict, indent=2)}")
                
                processed_event = await pipeline.process_single_event(event_dict)
                processed_events.append(processed_event)
                
                print(f"Event processed successfully: {json.dumps(processed_event, indent=2)}")
                
            except Exception as e:
                print(f"❌ Error processing event: {e}")
                traceback.print_exc()
                continue

        print(f"Successfully processed {len(processed_events)} events through pipeline")

        # Store in sinks
        print(f"\nWriting {len(processed_events)} events to sinks...")
        sink_results = await sinks_manager.write_events(processed_events)
        print(f"Sink write results: {sink_results}")
        
        # Check if Loki would have the right labels
        if processed_events:
            event = processed_events[0]
            print(f"\nFirst processed event labels that would go to Loki:")
            
            # Simulate Loki label extraction
            from app.storage.loki import LokiClient
            loki_client = LokiClient({"enabled": True, "url": "http://localhost:3100"})
            labels = loki_client._extract_safe_labels(event)
            print(f"Extracted labels: {labels}")
            
            # Check if it matches the query pattern
            if labels.get('source') == 'mothership':
                print("✅ Labels match query pattern {source=\"mothership\"}")
            else:
                print(f"❌ Labels don't match - source='{labels.get('source')}' != 'mothership'")
                
        await sinks_manager.stop()
        
        print("\n🎉 Ingestion simulation completed successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Ingestion simulation failed: {e}")
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = asyncio.run(test_exact_ingestion_payload())
    if not success:
        sys.exit(1)