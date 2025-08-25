#!/usr/bin/env python3
"""
Full pipeline test to debug the Loki regression test failure.

This script simulates the exact mothership processing pipeline to identify
where the data flow breaks down.
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

# Set environment exactly as in regression test
os.environ["LOKI_ENABLED"] = "true"
os.environ["LOKI_URL"] = "http://localhost:3100"
os.environ["TSDB_ENABLED"] = "true"  # But we won't use it
os.environ["TSDB_HOST"] = "localhost"
os.environ["TSDB_PORT"] = "5432"
os.environ["TSDB_DATABASE"] = "mothership"
os.environ["TSDB_USERNAME"] = "postgres"
os.environ["TSDB_PASSWORD"] = "postgres"
os.environ["MOTHERSHIP_DB_DSN"] = "postgresql://postgres:postgres@localhost:5432/mothership"

# Add mothership to path
sys.path.insert(0, str(Path(__file__).parent / "mothership"))

async def debug_full_pipeline():
    """Debug the full mothership pipeline processing."""
    
    print("🔍 Full pipeline debug test...\n")
    
    # Simulate exact test payload from regression
    test_id = "regress-1756105308"  # Use similar ID format
    
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
    
    print(f"✅ Test payload: {json.dumps(payload, indent=2)}")
    
    try:
        # Import mothership components
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
        print("📚 Loading configuration...")
        config_manager = ConfigManager()
        config = config_manager.get_config()
        print(f"   Enabled sinks: {config_manager.get_enabled_sinks()}")
        
        # Check Loki configuration specifically
        loki_config = config.get("sinks", {}).get("loki", {})
        print(f"   Loki config: {loki_config}")
        
        # Create pipeline exactly as in server.py
        print("🔧 Creating pipeline...")
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
            
        print(f"   Pipeline created with {len(pipeline.processors)} processors")
        
        # Create sinks manager (without TSDB writer to avoid DB dependency)
        print("🔌 Creating sinks manager...")
        sinks_manager = SinksManager(config, tsdb_writer=None)
        print(f"   Available sinks: {list(sinks_manager.sinks.keys())}")
        
        # Start sinks
        print("▶️ Starting sinks...")
        await sinks_manager.start()
        print("   Sinks started")
        
        # Process ingestion
        print("🔄 Processing events...")
        request = IngestRequest(**payload)
        events = request.messages
        
        processed_events = []
        for event in events:
            event_dict = event.model_dump()
            print(f"   Processing: {json.dumps(event_dict, indent=4)}")
            processed_event = await pipeline.process_single_event(event_dict)
            processed_events.append(processed_event)
            print(f"   Processed: {json.dumps(processed_event, indent=4)}")
                
        print(f"✅ Processed {len(processed_events)} events")

        # Write to sinks (the critical step)
        print("💾 Writing to sinks...")
        start_time = time.time()
        sink_results = await sinks_manager.write_events(processed_events)
        end_time = time.time()
        
        print(f"⏱️ Sink write completed in {end_time - start_time:.2f} seconds")
        print(f"📊 Sink results: {json.dumps(sink_results, indent=2)}")
        
        # Analyze results
        print("\n🎯 Analysis:")
        
        if "loki" in sink_results:
            loki_result = sink_results["loki"]
            written = loki_result.get("written", 0)
            queued = loki_result.get("queued", 0)
            errors = loki_result.get("errors", 0)
            
            print(f"   Loki: written={written}, queued={queued}, errors={errors}")
            
            if written > 0:
                print(f"   ✅ Data should be in Loki and queryable")
                
                # Test Loki entry format
                if processed_events:
                    from app.storage.loki import LokiClient
                    loki_client = LokiClient(loki_config)
                    loki_entry = loki_client._convert_to_loki_entry(processed_events[0])
                    
                    if loki_entry:
                        labels = loki_entry['labels']
                        line = loki_entry['line']
                        print(f"   📝 Loki entry:")
                        print(f"      Labels: {labels}")
                        print(f"      Line: {line}")
                        
                        # Check query compatibility
                        source_match = labels.get('source') == 'mothership'
                        id_match = test_id in line
                        print(f"      Query {test_id}: source_match={source_match}, id_match={id_match}")
                        
                        if source_match and id_match:
                            print(f"   ✅ Query {{source=\"mothership\"}} |= \"{test_id}\" SHOULD find this data")
                        else:
                            print(f"   ❌ Query would NOT find this data")
            else:
                print(f"   ❌ No data written to Loki (errors={errors})")
                print("   🔍 This is the root cause of the regression test failure")
        else:
            print(f"   ❌ Loki sink not present in results")
        
        await sinks_manager.stop()
        
        print(f"\n✅ Full pipeline test completed!")
        return sink_results.get("loki", {}).get("written", 0) > 0
        
    except Exception as e:
        print(f"❌ Pipeline test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = asyncio.run(debug_full_pipeline())
    if not success:
        print("\n🚨 DIAGNOSIS: Data is not being written to Loki successfully")
        print("This explains why the regression test Loki query returns empty results")
        sys.exit(1)
    else:
        print("\n🎉 SUCCESS: Data should reach Loki and be queryable")