#!/usr/bin/env python3
"""
Minimal test to reproduce the exact CI environment behavior where Loki sink returns written=0.
This test specifically focuses on reproducing the conditions that cause the regression test to fail.
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
os.environ["TSDB_ENABLED"] = "true"  # This is set in the CI but TSDB fails to connect
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

class MockLokiServer:
    """Mock Loki server that always returns success to isolate the sink behavior."""
    
    def __init__(self):
        self.received_data = []
        self.server = None
        
    async def start(self):
        """Start the mock Loki server."""
        from aiohttp import web, web_runner
        
        async def push_handler(request):
            data = await request.json()
            self.received_data.append(data)
            print(f"🔍 Mock Loki received data: {json.dumps(data, indent=2)}")
            # Return success like real Loki
            return web.Response(status=204)
        
        async def ready_handler(request):
            return web.Response(text="ready")
        
        app = web.Application()
        app.router.add_post('/loki/api/v1/push', push_handler)
        app.router.add_get('/ready', ready_handler)
        
        runner = web_runner.AppRunner(app)
        await runner.setup()
        site = web_runner.TCPSite(runner, 'localhost', 3100)
        await site.start()
        self.server = runner
        print("🔍 Mock Loki server started on http://localhost:3100")
        
    async def stop(self):
        if self.server:
            await self.server.cleanup()


async def test_ci_loki_reproduction():
    """Test reproduction of CI environment Loki sink behavior."""
    
    print("🔍 Testing CI environment Loki sink reproduction...\n")
    
    # Start mock Loki server
    mock_loki = MockLokiServer()
    await mock_loki.start()
    
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
        
        # Debug: Show what the processed event looks like
        if processed_events:
            event = processed_events[0]
            print(f"🔍 Processed event keys: {list(event.keys())}")
            print(f"🔍 Processed event message: {event.get('message', 'NO MESSAGE')}")
            print(f"🔍 Processed event source: {event.get('source', 'NO SOURCE')}")
        
        # Write to sinks (the critical part that's failing)
        print("\n🔍 Writing events to sinks...")
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
                print("✅ SUCCESS: Loki sink wrote events!")
            elif queued > 0:
                print("⚠️  WARNING: Events queued but not written yet")
            else:
                print("❌ PROBLEM: No events written or queued to Loki")
                
        else:
            print("❌ CRITICAL: No loki results in sink_results!")
            
        # Check if mock Loki received anything
        print(f"\n🔍 Mock Loki received {len(mock_loki.received_data)} requests")
        for i, data in enumerate(mock_loki.received_data):
            print(f"  Request {i+1}: {len(data.get('streams', []))} streams")
            
        # Wait a bit to see if batching affects results
        print("\n⏳ Waiting 2 seconds for any batch processing...")
        await asyncio.sleep(2)
        
        # Stop sinks to trigger any final flushes
        await sinks_manager.stop()
        
        print(f"\n🔍 After stop: Mock Loki received {len(mock_loki.received_data)} total requests")
        
        # Final analysis
        if mock_loki.received_data:
            print("✅ SUCCESS: Mock Loki received data - Loki sink is working!")
            return True
        else:
            print("❌ FAILURE: Mock Loki received no data - this reproduces the CI issue!")
            return False
            
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        await mock_loki.stop()


if __name__ == "__main__":
    success = asyncio.run(test_ci_loki_reproduction())
    if success:
        print("\n🎉 Test completed: Loki sink is working correctly")
    else:
        print("\n💥 Test reproduced the CI issue: Loki sink returns written=0")
        sys.exit(1)