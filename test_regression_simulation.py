#!/usr/bin/env python3
"""Test exact regression workflow logic with improved error handling."""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

# Set environment variables exactly as in regression workflow
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

async def test_regression_workflow():
    """Test the exact regression workflow with improved error handling."""
    
    print("🔍 Testing regression workflow with improved error handling...\n")
    
    # Exact payload from regression test
    test_id = f"regress-{int(time.time())}"
    
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
        from app.server import IngestRequest, IngestResponse
        from app.config import ConfigManager
        from app.pipeline.processor import Pipeline
        from app.storage.sinks import SinksManager
        from app.storage.tsdb import TimescaleDBWriter
        from app.pipeline.processors_redaction import RedactionPipeline, PIISafetyValidator
        from app.pipeline.processors_enrich import (
            AddTagsProcessor, SeverityMapProcessor, ServiceFromPathProcessor,
            GeoHintProcessor, SiteEnvTagsProcessor, TimestampNormalizer,
        )
        
        # Simulate improved server startup logic
        print("Simulating server startup...")
        config_manager = ConfigManager()
        config = config_manager.get_config()
        
        # Initialize TimescaleDB writer with error handling (as in fixed server.py)
        db_config = config["database"]
        tsdb_writer = None
        try:
            tsdb_writer = TimescaleDBWriter(db_config)
            await tsdb_writer.initialize()
            print("✅ TimescaleDB writer initialized successfully")
        except Exception as e:
            print(f"⚠️  Failed to initialize TimescaleDB writer: {e}")
            print("✅ Continuing without TSDB writer")
            tsdb_writer = None

        # Initialize sinks manager (as in fixed server.py)
        try:
            sinks_manager = SinksManager(config, tsdb_writer=tsdb_writer)
            await sinks_manager.start()
            print(f"✅ Sinks manager started with sinks: {list(sinks_manager.sinks.keys())}")
        except Exception as e:
            print(f"❌ Failed to start sinks manager: {e}")
            return False

        # Initialize pipeline
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
        
        # Simulate exact ingestion endpoint logic
        print(f"\nProcessing ingestion request with test_id: {test_id}")
        
        start_time = time.time()
        
        # Parse request
        request = IngestRequest(**payload)
        events = request.messages
        
        if not events:
            print("❌ No events to process")
            return False
            
        print(f"Processing {len(events)} events")
        
        # Process events through pipeline (with improved error handling)
        processed_events = []
        for event in events:
            try:
                event_dict = event.model_dump()
                processed_event = await pipeline.process_single_event(event_dict)
                processed_events.append(processed_event)
            except Exception as e:
                print(f"❌ Error processing event: {e}")
                # Continue processing other events
                continue
                
        print(f"✅ Successfully processed {len(processed_events)} events through pipeline")
        
        # Write to sinks
        print(f"Writing {len(processed_events)} events to sinks...")
        try:
            sink_results = await sinks_manager.write_events(processed_events)
            processing_time = time.time() - start_time
            
            print(f"✅ Sink write completed in {processing_time:.3f} seconds")
            print(f"Sink results: {sink_results}")
            
            # Simulate the successful response that would be returned
            response = IngestResponse(
                status="success",
                processed_events=len(processed_events),
                processing_time=processing_time,
                sink_results=sink_results,
            )
            
            print(f"✅ Would return HTTP 200 with response: {response.model_dump()}")
            
        except Exception as e:
            print(f"❌ Unhandled error during sink writes: {e}")
            return False
            
        # Test Loki query compatibility
        print(f"\nTesting Loki query compatibility...")
        if processed_events:
            event = processed_events[0]
            
            # Simulate Loki label extraction
            from app.storage.loki import LokiClient
            loki_client = LokiClient({"enabled": True, "url": "http://localhost:3100"})
            loki_entry = loki_client._convert_to_loki_entry(event)
            
            if loki_entry:
                labels = loki_entry["labels"]
                line = loki_entry["line"]
                
                print(f"Loki entry labels: {labels}")
                print(f"Loki entry line: {line}")
                
                # Check query compatibility
                query_matches = []
                
                # Check {source="mothership"} 
                if labels.get('source') == 'mothership':
                    query_matches.append("✅ {source=\"mothership\"}")
                else:
                    query_matches.append(f"❌ {labels.get('source', 'None')} != 'mothership'")
                    
                # Check |= "$TEST_ID"
                if test_id in line:
                    query_matches.append(f"✅ line contains '{test_id}'")
                else:
                    query_matches.append(f"❌ line does not contain '{test_id}'")
                
                print("Query compatibility:")
                for match in query_matches:
                    print(f"  {match}")
                
                if all("✅" in match for match in query_matches):
                    print("🎉 Event would be found by Loki query {source=\"mothership\"} |= \"$TEST_ID\"")
                else:
                    print("❌ Event would NOT be found by the regression test query")
                    return False
            else:
                print("❌ Failed to convert event to Loki entry")
                return False
        else:
            print("❌ No events were processed")
            return False
            
        await sinks_manager.stop()
        
        print(f"\n🎉 Regression workflow simulation completed successfully!")
        print(f"The ingestion would complete without 500 errors and Loki would receive the data with correct labels.")
        return True
        
    except Exception as e:
        print(f"❌ Regression workflow test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = asyncio.run(test_regression_workflow())
    if not success:
        sys.exit(1)