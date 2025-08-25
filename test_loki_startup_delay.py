#!/usr/bin/env python3
"""
Test to simulate Loki being "ready" but temporarily failing push requests,
which might be the actual issue in CI environment.
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

# CI environment flags (important for batching behavior)
os.environ["GITHUB_ACTIONS"] = "true"

# Add mothership to path
sys.path.insert(0, str(Path(__file__).parent / "mothership"))

class TemporaryFailingLokiServer:
    """Mock Loki server that responds to /ready but initially fails push requests."""
    
    def __init__(self, fail_for_seconds: int = 5):
        self.received_data = []
        self.server = None
        self.start_time = time.time()
        self.fail_for_seconds = fail_for_seconds
        
    async def start(self):
        """Start the mock Loki server."""
        from aiohttp import web, web_runner
        
        async def push_handler(request):
            elapsed = time.time() - self.start_time
            
            # Fail for the first few seconds to simulate startup delay
            if elapsed < self.fail_for_seconds:
                print(f"🔍 Mock Loki rejecting push (startup delay, {elapsed:.1f}s < {self.fail_for_seconds}s)")
                return web.Response(status=503, text="Service temporarily unavailable")
            
            # After startup delay, accept requests normally
            data = await request.json()
            self.received_data.append(data)
            print(f"🔍 Mock Loki accepted push (after {elapsed:.1f}s): {len(data.get('streams', []))} streams")
            return web.Response(status=204)
        
        async def ready_handler(request):
            # Always respond ready (like real Loki does)
            return web.Response(text="ready")
        
        app = web.Application()
        app.router.add_post('/loki/api/v1/push', push_handler)
        app.router.add_get('/ready', ready_handler)
        
        runner = web_runner.AppRunner(app)
        await runner.setup()
        site = web_runner.TCPSite(runner, 'localhost', 3100)
        await site.start()
        self.server = runner
        print(f"🔍 Mock Loki server started on http://localhost:3100 (will fail push for {self.fail_for_seconds}s)")
        
    async def stop(self):
        if self.server:
            await self.server.cleanup()


async def test_loki_startup_delay_scenario():
    """Test what happens when Loki is ready but has startup delay for ingestion."""
    
    print("🔍 Testing Loki startup delay scenario (might explain CI issues)...\n")
    
    # Start mock Loki with startup delay
    mock_loki = TemporaryFailingLokiServer(fail_for_seconds=3)
    await mock_loki.start()
    
    try:
        # Import required modules AFTER setting environment
        from app.config import ConfigManager
        from app.storage.sinks import SinksManager
        from app.server import IngestRequest
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
        
        # Initialize exactly like CI does
        config_manager = ConfigManager()
        config = config_manager._config
        print(f"🔍 Config enabled sinks: {config_manager.get_enabled_sinks()}")
        
        # Initialize sinks manager WITHOUT TimescaleDB (like CI when DB fails)
        sinks_manager = SinksManager(config, tsdb_writer=None)
        await sinks_manager.start()
        print(f"🔍 Sinks manager started with sinks: {sinks_manager.get_sink_names()}")
        
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
        
        print(f"🔍 Pipeline initialized with {len(pipeline.processors)} processors")
        
        # Test with immediate ingestion (might fail due to startup delay)
        test_id = f"regress-immediate-{int(time.time())}"
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
        
        print(f"🔍 Testing immediate ingestion (test_id: {test_id})")
        
        # Process events
        request = IngestRequest(**payload)
        events = request.messages
        
        processed_events = []
        for event in events:
            event_dict = event.model_dump()
            processed_event = await pipeline.process_single_event(event_dict)
            processed_events.append(processed_event)
            
        # Write to sinks immediately (like CI does)
        print("🔍 Writing events to sinks immediately...")
        start_time = time.time()
        sink_results = await sinks_manager.write_events(processed_events)
        write_time = time.time() - start_time
        
        print(f"✅ Immediate sink write completed in {write_time:.3f} seconds")
        print(f"🔍 Immediate sink results: {sink_results}")
        
        # Now test after delay (should succeed)
        print(f"\n🔍 Waiting 5 seconds for Loki startup delay to pass...")
        await asyncio.sleep(5)
        
        test_id_delayed = f"regress-delayed-{int(time.time())}"
        payload_delayed = {
            "messages": [
                {
                    "timestamp": "2025-01-01T00:00:00Z", 
                    "type": "syslog",
                    "message": f"Full regression test via GitHub Actions {test_id_delayed}",
                    "hostname": "actions-runner",
                    "severity": "info",
                    "_internal": "should_be_dropped",
                    "raw_message": "<14>Jan  1 00:00:00 actions app: Full regression test",
                    "tags": {"component":"regression","path":"edge->mothership","channel":"ci"}
                }
            ]
        }
        
        print(f"🔍 Testing delayed ingestion (test_id: {test_id_delayed})")
        
        # Process events
        request_delayed = IngestRequest(**payload_delayed)
        events_delayed = request_delayed.messages
        
        processed_events_delayed = []
        for event in events_delayed:
            event_dict = event.model_dump()
            processed_event = await pipeline.process_single_event(event_dict)
            processed_events_delayed.append(processed_event)
        
        # Write to sinks after delay
        print("🔍 Writing events to sinks after delay...")
        start_time = time.time()
        sink_results_delayed = await sinks_manager.write_events(processed_events_delayed)
        write_time = time.time() - start_time
        
        print(f"✅ Delayed sink write completed in {write_time:.3f} seconds")
        print(f"🔍 Delayed sink results: {sink_results_delayed}")
        
        # Analysis
        immediate_written = sink_results.get('loki', {}).get('written', 0)
        delayed_written = sink_results_delayed.get('loki', {}).get('written', 0)
        
        print(f"\n📊 Analysis:")
        print(f"  - Immediate write (startup delay): written={immediate_written}")
        print(f"  - Delayed write (after startup): written={delayed_written}")
        print(f"  - Mock Loki received {len(mock_loki.received_data)} total requests")
        
        if immediate_written == 0 and delayed_written > 0:
            print("🎯 FOUND THE ISSUE: Loki startup delay causes immediate writes to fail!")
            print("This explains why CI regression tests fail - timing issue!")
            return True
        elif immediate_written > 0:
            print("✅ Fixed: Immediate writes now succeed even with startup delay")
            return True
        else:
            print("❓ Unexpected: Both immediate and delayed writes failed")
            return False
            
        # Stop sinks
        await sinks_manager.stop()
        
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        await mock_loki.stop()


if __name__ == "__main__":
    success = asyncio.run(test_loki_startup_delay_scenario())
    if success:
        print("\n🎯 Test completed successfully")
    else:
        print("\n❓ Test completed but with unexpected results")
        sys.exit(1)