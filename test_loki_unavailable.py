#!/usr/bin/env python3
"""
Test to reproduce the exact CI failure where Loki is unavailable,
which should explain why the regression test returns written=0.
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

# Set the EXACT environment variables used in CI regression test
os.environ["LOKI_ENABLED"] = "true"
os.environ["LOKI_URL"] = "http://localhost:3100"  # This will be unavailable
os.environ["TSDB_ENABLED"] = "true"  
os.environ["TSDB_HOST"] = "localhost"
os.environ["TSDB_PORT"] = "5432"
os.environ["TSDB_DATABASE"] = "mothership"
os.environ["TSDB_USERNAME"] = "postgres"
os.environ["TSDB_PASSWORD"] = "postgres"
os.environ["MOTHERSHIP_DB_DSN"] = "postgresql://postgres:postgres@localhost:5432/mothership"
os.environ["MOTHERSHIP_LOG_LEVEL"] = "INFO"

# CI environment flags (important for batching behavior)
os.environ["GITHUB_ACTIONS"] = "true"

# Add mothership to path
sys.path.insert(0, str(Path(__file__).parent / "mothership"))

async def test_loki_unavailable_scenario():
    """Test what happens when Loki is enabled but unavailable (CI scenario)."""
    
    print("🔍 Testing Loki unavailable scenario (reproducing CI failure)...\n")
    
    # DO NOT start any mock server - let Loki be unavailable like in CI
    
    try:
        # Import required modules AFTER setting environment
        from app.config import ConfigManager
        from app.storage.sinks import SinksManager
        from app.storage.loki import LokiClient
        from app.server import IngestRequest, IngestResponse
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
        
        print("✅ Successfully imported all modules")
        
        # Initialize exactly like CI does (with no database)
        config_manager = ConfigManager()
        config = config_manager._config  # Access the private config attribute
        print(f"🔍 Config enabled sinks: {config_manager.get_enabled_sinks()}")
        
        # Initialize sinks manager WITHOUT TimescaleDB (like CI when DB fails)
        sinks_manager = SinksManager(config, tsdb_writer=None)
        await sinks_manager.start()
        print(f"🔍 Sinks manager started with sinks: {sinks_manager.get_sink_names()}")
        
        # Initialize pipeline exactly like server does
        pipeline = Pipeline(config["pipeline"])
        processor_config = config["pipeline"]["processors"]
        
        # Add processors in the same order as server
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
        
        print(f"🔍 Pipeline initialized with {len(pipeline.processors)} processors")
        
        # Create the EXACT payload used in regression test
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
        
        print(f"🔍 Processing test_id: {test_id}")
        
        # Process events through pipeline (exactly like server does)
        request = IngestRequest(**payload)
        events = request.messages
        
        processed_events = []
        for event in events:
            event_dict = event.model_dump()
            processed_event = await pipeline.process_single_event(event_dict)
            processed_events.append(processed_event)
            
        print(f"✅ Processed {len(processed_events)} events through pipeline")
        
        # Write to sinks (the critical part that's failing in CI)
        print("\n🔍 Writing events to sinks with Loki unavailable...")
        start_time = time.time()
        sink_results = await sinks_manager.write_events(processed_events)
        write_time = time.time() - start_time
        
        print(f"✅ Sink write completed in {write_time:.3f} seconds")
        print(f"🔍 Sink results: {sink_results}")
        
        # Analyze the results
        if 'loki' in sink_results:
            loki_result = sink_results['loki']
            written = loki_result.get('written', 0)
            queued = loki_result.get('queued', 0)
            errors = loki_result.get('errors', 0)
            
            print(f"\n📊 Loki sink analysis:")
            print(f"  - Written: {written}")
            print(f"  - Queued: {queued}")
            print(f"  - Errors: {errors}")
            
            if written > 0:
                print("❌ UNEXPECTED: Loki sink wrote events even though Loki is unavailable!")
                return False
            elif queued > 0:
                print("⚠️  Expected: Events queued but not written (Loki unavailable)")
                print("🎯 This explains the CI issue: Loki returns written=0 when unavailable")
                return True
            elif errors > 0:
                print("✅ Expected: Errors when Loki is unavailable")
                print("🎯 This explains the CI issue: Loki returns written=0, errors>0")
                return True
            else:
                print("🤔 Unexpected: No events written, queued, or errors")
                return False
                
        else:
            print("❌ CRITICAL: No loki results in sink_results!")
            return False
            
        # Stop sinks to trigger any final flushes
        await sinks_manager.stop()
        
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = asyncio.run(test_loki_unavailable_scenario())
    if success:
        print("\n🎯 SUCCESS: Reproduced the CI issue - Loki returns written=0 when unavailable")
        print("This explains why the regression test fails!")
    else:
        print("\n❓ Could not reproduce the CI issue")
        sys.exit(1)