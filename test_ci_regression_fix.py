#!/usr/bin/env python3
"""Test to reproduce the exact CI regression failure scenario."""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

# Add mothership to path
sys.path.insert(0, str(Path(__file__).parent / "mothership"))

from app.config import ConfigManager
from app.server import IngestRequest
from app.pipeline.pipeline import Pipeline
from app.storage.sinks import SinksManager
from app.pipeline.processors import *


async def test_ci_regression_scenario():
    """Simulate the exact CI regression test scenario."""
    print("🔍 Testing CI regression scenario...")
    
    # Set CI environment variables
    os.environ['GITHUB_ACTIONS'] = 'true'
    os.environ['MOTHERSHIP_LOG_LEVEL'] = 'INFO'
    os.environ['LOKI_ENABLED'] = 'true'
    os.environ['LOKI_URL'] = 'http://localhost:3100'
    
    # Use the same test ID pattern as CI
    test_id = f"regress-{int(time.time())}"
    
    # Exact payload from CI
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
    
    print(f"Test ID: {test_id}")
    
    try:
        # Load config with exact CI settings
        config_manager = ConfigManager()
        config = config_manager.load_config()
        
        # Force TSDB disabled
        config['tsdb']['enabled'] = False
        
        print(f"Loki config: {config['loki']}")
        print(f"TSDB enabled: {config['tsdb']['enabled']}")
        
        # Create pipeline (same as CI)
        pipeline = Pipeline()
        
        # Add processors in the same order as the actual server
        redact_config = config.get('data_processing', {}).get('redaction', {})
        redact_processor = RedactionProcessor(redact_config)
        pipeline.add_processor(redact_processor)
        
        enrich_config = config.get('data_processing', {}).get('enrichment', {})
        hostname_processor = HostnameExtractorProcessor(enrich_config)
        pipeline.add_processor(hostname_processor)
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
        
        # Create sinks manager
        sinks_manager = SinksManager(config, tsdb_writer=None)
        print(f"Sinks available: {list(sinks_manager.sinks.keys())}")
        
        await sinks_manager.start()
        
        # Process the request
        request = IngestRequest(**payload)
        events = request.messages
        
        processed_events = []
        for event in events:
            event_dict = event.model_dump()
            processed_event = await pipeline.process_single_event(event_dict)
            processed_events.append(processed_event)
        
        print(f"Processed event: {json.dumps(processed_events[0], indent=2)}")
        
        # Check what labels will be generated
        from app.storage.loki import LokiClient
        loki_client = LokiClient(config['loki'])
        labels = loki_client._extract_safe_labels(processed_events[0])
        loki_entry = loki_client._convert_to_loki_entry(processed_events[0])
        
        print(f"\nLoki labels: {labels}")
        print(f"Loki entry: {loki_entry}")
        
        # Check if query pattern would match
        source_matches = labels.get('source') == 'mothership'
        message_matches = test_id in loki_entry.get('line', '') if loki_entry else False
        
        print(f"\nQuery pattern analysis:")
        print(f"  source='mothership': {source_matches} (actual: '{labels.get('source')}')")
        print(f"  contains '{test_id}': {message_matches}")
        print(f"  Expected query: {{source=\"mothership\"}} |= \"{test_id}\"")
        
        if source_matches and message_matches:
            print("✅ Query pattern would match the event")
        else:
            print("❌ Query pattern would NOT match the event")
            return False
        
        # Now test the actual write to Loki
        print(f"\n🔄 Writing to Loki...")
        start_time = time.time()
        sink_results = await sinks_manager.write_events(processed_events)
        write_time = time.time() - start_time
        
        print(f"Write completed in {write_time:.3f}s")
        print(f"Sink results: {sink_results}")
        
        # Analyze the result
        loki_result = sink_results.get('loki', {})
        written = loki_result.get('written', 0)
        errors = loki_result.get('errors', 0)
        
        if written > 0 and errors == 0:
            print("✅ Loki write reported success")
            success = True
        elif written == 0 and errors > 0:
            print("❌ Loki write reported failure")
            success = False
        else:
            print(f"⚠️  Loki write reported partial success/failure: written={written}, errors={errors}")
            success = written > 0
        
        await sinks_manager.stop()
        
        return success, test_id, loki_result
        
    except Exception as e:
        print(f"❌ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        return False, test_id, {}


if __name__ == "__main__":
    asyncio.run(test_ci_regression_scenario())