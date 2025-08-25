#!/usr/bin/env python3
"""Test to validate the Loki fix with a mock Loki server."""

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, Any
import httpx
from aiohttp import web, ClientTimeout
import threading

# Add mothership to path
sys.path.insert(0, str(Path(__file__).parent / "mothership"))


class MockLokiServer:
    """Mock Loki server for testing."""
    
    def __init__(self, port: int = 3100):
        self.port = port
        self.app = web.Application()
        self.received_events = []
        self.ready = True  # Can be set to False to simulate not ready
        self.response_delay = 0.0  # Simulate slow responses
        self.setup_routes()
        
    def setup_routes(self):
        """Setup mock Loki API routes."""
        self.app.router.add_get('/ready', self.ready_handler)
        self.app.router.add_post('/loki/api/v1/push', self.push_handler)
        self.app.router.add_get('/loki/api/v1/query_range', self.query_handler)
        
    async def ready_handler(self, request):
        """Handle /ready endpoint."""
        if self.response_delay > 0:
            await asyncio.sleep(self.response_delay)
            
        if self.ready:
            return web.Response(status=200, text="ready")
        else:
            return web.Response(status=503, text="not ready")
    
    async def push_handler(self, request):
        """Handle /loki/api/v1/push endpoint."""
        if self.response_delay > 0:
            await asyncio.sleep(self.response_delay)
            
        try:
            data = await request.json()
            
            # Store received events for later verification
            for stream in data.get('streams', []):
                for timestamp, line in stream.get('values', []):
                    self.received_events.append({
                        'labels': stream.get('stream', {}),
                        'timestamp': timestamp,
                        'line': line
                    })
            
            print(f"Mock Loki received {len(data.get('streams', []))} streams with {len(self.received_events)} total events")
            return web.Response(status=204)  # Loki returns 204 on successful ingest
            
        except Exception as e:
            print(f"Mock Loki push handler error: {e}")
            return web.Response(status=400, text=str(e))
    
    async def query_handler(self, request):
        """Handle /loki/api/v1/query_range endpoint."""
        if self.response_delay > 0:
            await asyncio.sleep(self.response_delay)
            
        query = request.query.get('query', '')
        
        # Simple query matching - just check if any events match
        matching_events = []
        
        for event in self.received_events:
            labels = event['labels']
            line = event['line']
            
            # Parse the query (very basic parsing for testing)
            if 'source="mothership"' in query:
                if labels.get('source') != 'mothership':
                    continue
                    
            # Check for |= "text" matching
            if '|=' in query:
                search_text = query.split('|=')[1].strip().strip('"')
                if search_text not in line:
                    continue
                    
            matching_events.append(event)
        
        # Format response like Loki
        result = []
        if matching_events:
            # Group by labels for response
            streams = {}
            for event in matching_events:
                labels_key = json.dumps(event['labels'], sort_keys=True)
                if labels_key not in streams:
                    streams[labels_key] = {
                        'stream': event['labels'],
                        'values': []
                    }
                streams[labels_key]['values'].append([event['timestamp'], event['line']])
            
            result = list(streams.values())
        
        response = {
            "status": "success",
            "data": {
                "resultType": "streams",
                "result": result,
                "stats": {
                    "summary": {
                        "totalEntriesReturned": len(matching_events)
                    }
                }
            }
        }
        
        print(f"Mock Loki query '{query}' returned {len(matching_events)} events")
        return web.json_response(response)


async def test_with_mock_loki():
    """Test Loki client with mock server."""
    print("🔍 Testing with mock Loki server...")
    
    # Set CI environment variables
    os.environ['GITHUB_ACTIONS'] = 'true'
    os.environ['MOTHERSHIP_LOG_LEVEL'] = 'INFO'
    os.environ['LOKI_ENABLED'] = 'true'
    os.environ['LOKI_URL'] = 'http://localhost:3100'
    
    test_id = f"regress-{int(time.time())}"
    print(f"Test ID: {test_id}")
    
    # Start mock Loki server
    mock_server = MockLokiServer()
    
    runner = web.AppRunner(mock_server.app)
    await runner.setup()
    site = web.TCPSite(runner, 'localhost', 3100)
    await site.start()
    print("✅ Mock Loki server started on http://localhost:3100")
    
    try:
        from app.storage.loki import LokiClient
        
        # Test 1: Basic successful write
        print(f"\n📝 Test 1: Basic successful write")
        
        config = {
            'enabled': True,
            'url': 'http://localhost:3100',
            'batch_size': 10,
            'batch_timeout_seconds': 2.0,
            'max_retries': 3
        }
        
        loki_client = LokiClient(config)
        print(f"CI environment detected: {loki_client._is_ci_environment()}")
        
        test_event = {
            "timestamp": "2025-01-01T00:00:00Z",
            "type": "syslog", 
            "message": f"Full regression test via GitHub Actions {test_id}",
            "hostname": "actions-runner",
            "severity": "info",
            "service": "actions-runner",
            "source": "mothership"
        }
        
        await loki_client.start()
        
        # Write event
        result = await loki_client.write_events([test_event])
        print(f"Write result: {result}")
        
        # Verify success
        if result.get('written', 0) > 0 and result.get('errors', 0) == 0:
            print("✅ Test 1 PASSED: Write succeeded")
            test1_success = True
        else:
            print("❌ Test 1 FAILED: Write failed")
            test1_success = False
        
        await loki_client.stop()
        
        # Test 2: Query verification  
        print(f"\n🔍 Test 2: Query verification")
        
        # Simulate the CI query
        query = f'{{source="mothership"}} |= "{test_id}"'
        
        async with httpx.AsyncClient() as client:
            # Use a time range that should include our event
            start_ns = 1735689600000000000  # 2025-01-01T00:00:00Z in nanoseconds  
            end_ns = int(time.time() * 1000000000)  # Now
            
            response = await client.get(
                "http://localhost:3100/loki/api/v1/query_range",
                params={
                    "query": query,
                    "start": str(start_ns),
                    "end": str(end_ns),
                    "limit": "1000"
                }
            )
            
            print(f"Query response status: {response.status_code}")
            
            if response.status_code == 200:
                query_data = response.json()
                print(f"Query data: {json.dumps(query_data, indent=2)}")
                
                matches = len(query_data.get('data', {}).get('result', []))
                total_entries = query_data.get('data', {}).get('stats', {}).get('summary', {}).get('totalEntriesReturned', 0)
                
                if matches > 0 and total_entries > 0:
                    print("✅ Test 2 PASSED: Query found the event")
                    test2_success = True
                else:
                    print("❌ Test 2 FAILED: Query did not find the event")
                    test2_success = False
            else:
                print(f"❌ Test 2 FAILED: Query request failed with status {response.status_code}")
                test2_success = False
        
        # Test 3: Delayed readiness (simulating CI timing issues)
        print(f"\n⏱️  Test 3: Delayed readiness scenario")
        
        # Reset mock server state
        mock_server.received_events.clear()
        mock_server.ready = False  # Start as not ready
        mock_server.response_delay = 1.0  # 1 second delay
        
        # Start a task to make Loki ready after 5 seconds
        async def make_ready_later():
            await asyncio.sleep(5)
            mock_server.ready = True
            mock_server.response_delay = 0.1  # Reduce delay once ready
            print("✅ Mock Loki is now ready")
        
        ready_task = asyncio.create_task(make_ready_later())
        
        test_id_3 = f"regress-delayed-{int(time.time())}"
        test_event_3 = {
            "timestamp": "2025-01-01T00:00:00Z",
            "type": "syslog", 
            "message": f"Delayed readiness test {test_id_3}",
            "hostname": "actions-runner",
            "severity": "info",
            "service": "actions-runner",
            "source": "mothership"
        }
        
        loki_client_3 = LokiClient(config)
        await loki_client_3.start()
        
        # This should wait for Loki to become ready and then succeed
        start_time = time.time()
        result_3 = await loki_client_3.write_events([test_event_3])
        write_time = time.time() - start_time
        
        print(f"Delayed write completed in {write_time:.1f}s")
        print(f"Delayed write result: {result_3}")
        
        if result_3.get('written', 0) > 0 and result_3.get('errors', 0) == 0:
            print("✅ Test 3 PASSED: Delayed readiness handled correctly")
            test3_success = True
        else:
            print("❌ Test 3 FAILED: Delayed readiness not handled")
            test3_success = False
        
        await loki_client_3.stop()
        await ready_task
        
        # Overall result
        overall_success = test1_success and test2_success and test3_success
        print(f"\n🎯 Overall Result:")
        print(f"  Test 1 (Basic write): {'✅ PASS' if test1_success else '❌ FAIL'}")
        print(f"  Test 2 (Query verification): {'✅ PASS' if test2_success else '❌ FAIL'}")
        print(f"  Test 3 (Delayed readiness): {'✅ PASS' if test3_success else '❌ FAIL'}")
        print(f"  Overall: {'🎉 SUCCESS' if overall_success else '💥 FAILURE'}")
        
        return overall_success
        
    except Exception as e:
        print(f"❌ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        # Clean up mock server
        await runner.cleanup()
        print("🧹 Mock Loki server stopped")


if __name__ == "__main__":
    result = asyncio.run(test_with_mock_loki())
    if result:
        print("🎉 All tests passed! The Loki fix should work in CI.")
        sys.exit(0)
    else:
        print("💥 Tests failed. More work needed.")
        sys.exit(1)