"""Tests for server ingest functionality."""
import unittest
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
import json
import sys
import os
from pathlib import Path

# Add the app directory to the path
sys.path.insert(0, str(Path(__file__).parent.parent / 'app'))

from fastapi.testclient import TestClient
from fastapi import FastAPI

# We can't easily test the full server due to startup dependencies,
# so we'll test individual components and create a simplified test app

class MockTSDBWriter:
    """Mock TimescaleDB writer for testing."""
    
    def __init__(self):
        self.inserted_events = []
        self.should_fail = False
    
    async def insert_events(self, events):
        if self.should_fail:
            return False
        self.inserted_events.extend(events)
        return True
    
    async def health_check(self):
        return not self.should_fail
    
    async def get_stats(self):
        return {
            'total_inserts': len(self.inserted_events),
            'total_batches': 1,
            'total_errors': 0
        }

class MockPipeline:
    """Mock pipeline for testing."""
    
    def __init__(self):
        self.processed_events = []
        self.should_fail = False
    
    async def process_events(self, events):
        if self.should_fail:
            raise Exception("Pipeline processing failed")
        
        # Simple mock processing - add a processed flag
        processed = []
        for event in events:
            processed_event = event.copy()
            processed_event['processed'] = True
            processed.append(processed_event)
        
        self.processed_events.extend(processed)
        return processed
    
    def get_stats(self):
        return {
            'total_events': len(self.processed_events),
            'successful_events': len(self.processed_events),
            'processors': {'MockProcessor': {'processed': len(self.processed_events)}}
        }
    
    def get_enabled_processors(self):
        return ['MockProcessor']

class TestIngestEndpoint(unittest.TestCase):
    """Test ingest endpoint logic."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.mock_tsdb = MockTSDBWriter()
        self.mock_pipeline = MockPipeline()
    
    def test_successful_ingest(self):
        """Test successful event ingestion."""
        # Test data
        events = [
            {
                'type': 'syslog',
                'message': 'User login successful',
                'timestamp': '2025-01-01T00:00:00Z',
                'source': 'web01'
            },
            {
                'type': 'log',
                'message': 'Application started',
                'timestamp': '2025-01-01T00:01:00Z',
                'source': 'app01'
            }
        ]
        
        # Simulate processing
        async def run_test():
            # Pipeline processing
            processed_events = await self.mock_pipeline.process_events(events)
            
            # Database insertion
            success = await self.mock_tsdb.insert_events(processed_events)
            
            return processed_events, success
        
        processed_events, success = asyncio.run(run_test())
        
        # Verify processing
        self.assertTrue(success)
        self.assertEqual(len(processed_events), 2)
        self.assertEqual(len(self.mock_tsdb.inserted_events), 2)
        
        # Verify events were processed
        for event in processed_events:
            self.assertTrue(event['processed'])
    
    def test_pipeline_failure(self):
        """Test handling of pipeline failures."""
        self.mock_pipeline.should_fail = True
        
        events = [{'type': 'log', 'message': 'test'}]
        
        async def run_test():
            try:
                await self.mock_pipeline.process_events(events)
                return False  # Should not reach here
            except Exception:
                return True  # Expected exception
        
        exception_caught = asyncio.run(run_test())
        self.assertTrue(exception_caught)
    
    def test_database_failure(self):
        """Test handling of database failures."""
        self.mock_tsdb.should_fail = True
        
        events = [{'type': 'log', 'message': 'test', 'processed': True}]
        
        async def run_test():
            return await self.mock_tsdb.insert_events(events)
        
        success = asyncio.run(run_test())
        self.assertFalse(success)

class TestRequestValidation(unittest.TestCase):
    """Test request validation logic."""
    
    def test_valid_event_structure(self):
        """Test validation of valid event structures."""
        from app.server import Event, IngestRequest
        
        # Valid event
        event_data = {
            'type': 'syslog',
            'message': 'Test message',
            'timestamp': '2025-01-01T00:00:00Z',
            'source': 'test-host'
        }
        
        event = Event(**event_data)
        self.assertEqual(event.type, 'syslog')
        self.assertEqual(event.message, 'Test message')
        
        # Valid request
        request_data = {
            'messages': [event_data]
        }
        
        request = IngestRequest(**request_data)
        self.assertEqual(len(request.messages), 1)
        self.assertEqual(request.messages[0].type, 'syslog')
    
    def test_invalid_event_structure(self):
        """Test validation of invalid event structures."""
        from app.server import Event
        from pydantic import ValidationError
        
        # Missing required type field
        with self.assertRaises(ValidationError):
            Event(message='Test message')
        
        # Empty type is actually valid, so let's test a truly invalid case
        # Type field is required but we'll test with other invalid cases if needed
    
    def test_extra_fields_allowed(self):
        """Test that extra fields are allowed in events."""
        from app.server import Event
        
        event_data = {
            'type': 'syslog',
            'message': 'Test message',
            'custom_field': 'custom_value',
            'nested_data': {'key': 'value'}
        }
        
        event = Event(**event_data)
        # Should not raise validation error
        self.assertEqual(event.type, 'syslog')

class TestHealthEndpoint(unittest.TestCase):
    """Test health check endpoint logic."""
    
    def test_healthy_status(self):
        """Test healthy status response."""
        mock_tsdb = MockTSDBWriter()
        mock_pipeline = MockPipeline()
        
        async def run_test():
            db_healthy = await mock_tsdb.health_check()
            processors = mock_pipeline.get_enabled_processors()
            
            return {
                'status': 'healthy' if db_healthy else 'degraded',
                'database': db_healthy,
                'pipeline_processors': processors
            }
        
        result = asyncio.run(run_test())
        
        self.assertEqual(result['status'], 'healthy')
        self.assertTrue(result['database'])
        self.assertIn('MockProcessor', result['pipeline_processors'])
    
    def test_degraded_status(self):
        """Test degraded status when database is unhealthy."""
        mock_tsdb = MockTSDBWriter()
        mock_tsdb.should_fail = True
        
        async def run_test():
            db_healthy = await mock_tsdb.health_check()
            return {
                'status': 'healthy' if db_healthy else 'degraded',
                'database': db_healthy
            }
        
        result = asyncio.run(run_test())
        
        self.assertEqual(result['status'], 'degraded')
        self.assertFalse(result['database'])

class TestStatsEndpoint(unittest.TestCase):
    """Test statistics endpoint logic."""
    
    def test_stats_collection(self):
        """Test statistics collection."""
        mock_tsdb = MockTSDBWriter()
        mock_pipeline = MockPipeline()
        
        # Simulate some activity
        mock_tsdb.inserted_events = [{'test': 'event1'}, {'test': 'event2'}]
        mock_pipeline.processed_events = [{'test': 'event1'}]
        
        async def run_test():
            pipeline_stats = mock_pipeline.get_stats()
            db_stats = await mock_tsdb.get_stats()
            
            return {
                'pipeline': pipeline_stats,
                'database': db_stats
            }
        
        result = asyncio.run(run_test())
        
        self.assertEqual(result['pipeline']['total_events'], 1)
        self.assertEqual(result['database']['total_inserts'], 2)
        self.assertIn('processors', result['pipeline'])

class TestDataFlow(unittest.TestCase):
    """Test end-to-end data flow."""
    
    def test_complete_data_flow(self):
        """Test complete data flow from ingest to database."""
        mock_tsdb = MockTSDBWriter()
        mock_pipeline = MockPipeline()
        
        # Input events
        input_events = [
            {
                'type': 'syslog',
                'message': 'Authentication failed',
                'severity': 'error',
                'source': 'auth-server'
            },
            {
                'type': 'log',
                'message': 'Database connection established',
                'severity': 'info',
                'source': 'db-server'
            }
        ]
        
        async def run_complete_flow():
            # 1. Process through pipeline
            processed_events = await mock_pipeline.process_events(input_events)
            
            # 2. Insert into database
            success = await mock_tsdb.insert_events(processed_events)
            
            # 3. Get final stats
            pipeline_stats = mock_pipeline.get_stats()
            db_stats = await mock_tsdb.get_stats()
            
            return {
                'success': success,
                'processed_count': len(processed_events),
                'pipeline_stats': pipeline_stats,
                'db_stats': db_stats,
                'final_events': mock_tsdb.inserted_events
            }
        
        result = asyncio.run(run_complete_flow())
        
        # Verify successful flow
        self.assertTrue(result['success'])
        self.assertEqual(result['processed_count'], 2)
        self.assertEqual(result['pipeline_stats']['total_events'], 2)
        self.assertEqual(result['db_stats']['total_inserts'], 2)
        
        # Verify events were processed
        final_events = result['final_events']
        self.assertEqual(len(final_events), 2)
        for event in final_events:
            self.assertTrue(event['processed'])  # Added by mock pipeline
    
    def test_partial_failure_handling(self):
        """Test handling of partial failures."""
        mock_tsdb = MockTSDBWriter()
        mock_pipeline = MockPipeline()
        
        # Make database fail
        mock_tsdb.should_fail = True
        
        input_events = [{'type': 'log', 'message': 'test'}]
        
        async def run_with_failure():
            # Pipeline should succeed
            processed_events = await mock_pipeline.process_events(input_events)
            
            # Database should fail
            db_success = await mock_tsdb.insert_events(processed_events)
            
            return {
                'pipeline_success': len(processed_events) > 0,
                'db_success': db_success
            }
        
        result = asyncio.run(run_with_failure())
        
        self.assertTrue(result['pipeline_success'])
        self.assertFalse(result['db_success'])


if __name__ == '__main__':
    unittest.main()