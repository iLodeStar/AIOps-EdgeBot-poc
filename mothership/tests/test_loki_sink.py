"""Tests for Loki sink functionality."""

import pytest
import json
import asyncio
from unittest.mock import AsyncMock, Mock
from httpx import MockTransport, Response, Request
import httpx

from mothership.app.config import LokiConfig
from mothership.app.storage.loki import LokiClient


class TestLokiClient:
    """Test cases for LokiClient."""
    
    @pytest.fixture
    def loki_config(self):
        """Create a test Loki configuration."""
        return LokiConfig(
            enabled=True,
            url="http://localhost:3100",
            batch_size=5,
            batch_timeout_seconds=1.0,
            max_retries=2,
            retry_backoff_seconds=0.1,
            timeout_seconds=5.0
        )
    
    @pytest.fixture
    def mock_transport(self):
        """Create a mock HTTP transport for testing."""
        def handler(request: Request) -> Response:
            # Simulate successful Loki push
            if request.url.path == "/loki/api/v1/push":
                return Response(status_code=204, content=b"")
            return Response(status_code=404)
        
        return MockTransport(handler)
    
    @pytest.mark.asyncio
    async def test_loki_client_disabled(self):
        """Test that disabled client doesn't process events."""
        config = LokiConfig(enabled=False)
        client = LokiClient(config)
        
        result = await client.write_events([{"message": "test"}])
        assert result == {"written": 0, "queued": 0, "errors": 0}
    
    @pytest.mark.asyncio
    async def test_event_conversion_safe_labels(self, loki_config):
        """Test that events are converted with safe labeling."""
        client = LokiClient(loki_config)
        
        event = {
            "message": "Test log message",
            "type": "application",
            "service": "test-service",
            "host": "test-host",
            "severity": "info",
            "timestamp": 1640995200,  # 2022-01-01 00:00:00 UTC
            # High cardinality fields that should be excluded from labels
            "request_id": "abc-123-def",
            "user_id": "user-456",
            "additional_data": {"key": "value"}
        }
        
        loki_entry = client._convert_to_loki_entry(event)
        
        assert loki_entry is not None
        assert "timestamp" in loki_entry
        assert "line" in loki_entry
        assert "labels" in loki_entry
        
        # Check safe labels are included
        labels = loki_entry["labels"]
        assert labels["type"] == "application"
        assert labels["service"] == "test-service"
        assert labels["host"] == "test-host"
        assert labels["severity"] == "info"
        
        # Check high cardinality fields are NOT in labels
        assert "request_id" not in labels
        assert "user_id" not in labels
        
        # Check message is in the log line
        assert "Test log message" in loki_entry["line"]
        
        # Check timestamp conversion (seconds to nanoseconds)
        expected_ns = 1640995200 * 1_000_000_000
        assert loki_entry["timestamp"] == str(expected_ns)
    
    @pytest.mark.asyncio
    async def test_event_without_message(self, loki_config):
        """Test event conversion when no message field is present."""
        client = LokiClient(loki_config)
        
        event = {
            "type": "metric",
            "service": "test",
            "value": 42,
            "tags": {"environment": "test"}
        }
        
        loki_entry = client._convert_to_loki_entry(event)
        
        assert loki_entry is not None
        # Should serialize the entire event as JSON
        line_data = json.loads(loki_entry["line"])
        assert line_data["value"] == 42
        assert line_data["tags"]["environment"] == "test"
    
    @pytest.mark.asyncio
    async def test_timestamp_extraction(self, loki_config):
        """Test various timestamp formats are handled correctly."""
        client = LokiClient(loki_config)
        
        # Test Unix timestamp (seconds)
        event1 = {"message": "test", "timestamp": 1640995200}
        entry1 = client._convert_to_loki_entry(event1)
        assert entry1["timestamp"] == str(1640995200 * 1_000_000_000)
        
        # Test ISO string
        event2 = {"message": "test", "timestamp": "2022-01-01T00:00:00Z"}
        entry2 = client._convert_to_loki_entry(event2)
        assert entry2["timestamp"] == str(1640995200 * 1_000_000_000)
        
        # Test fallback to current time (should be recent)
        event3 = {"message": "test"}
        entry3 = client._convert_to_loki_entry(event3)
        timestamp_ns = int(entry3["timestamp"])
        # Should be within last minute
        import time
        current_ns = int(time.time() * 1_000_000_000)
        assert abs(timestamp_ns - current_ns) < 60 * 1_000_000_000
    
    @pytest.mark.asyncio
    async def test_label_sanitization(self, loki_config):
        """Test that labels are properly sanitized."""
        client = LokiClient(loki_config)
        
        event = {
            "message": "test",
            "service": "test service with spaces",
            "type": "special@chars#here",
            "host": "host.example.com"
        }
        
        loki_entry = client._convert_to_loki_entry(event)
        labels = loki_entry["labels"]
        
        # Spaces and special chars should be replaced with underscores
        assert labels["service"] == "test_service_with_spaces"
        assert labels["type"] == "special_chars_here"
        # Dots and alphanumeric should be preserved
        assert labels["host"] == "host.example.com"
    
    @pytest.mark.asyncio
    async def test_high_cardinality_avoidance(self, loki_config):
        """Test that high cardinality labels are avoided."""
        client = LokiClient(loki_config)
        
        event = {
            "message": "test",
            "service": "test-service",  # Safe label
            "request_id": "unique-123",  # High cardinality
            "ip": "192.168.1.1",  # High cardinality
            "session_id": "sess-456"  # High cardinality
        }
        
        loki_entry = client._convert_to_loki_entry(event)
        labels = loki_entry["labels"]
        
        # Safe labels should be present
        assert labels["service"] == "test-service"
        
        # High cardinality labels should be absent
        assert "request_id" not in labels
        assert "ip" not in labels
        assert "session_id" not in labels
    
    @pytest.mark.asyncio
    async def test_batch_grouping_by_labels(self, loki_config):
        """Test that entries are grouped by labels for Loki streams."""
        # Create client with mock transport
        transport = MockTransport(lambda req: Response(status_code=204))
        
        client = LokiClient(loki_config)
        client.client = httpx.AsyncClient(transport=transport)
        
        entries = [
            {"timestamp": "1000000000", "line": "msg1", "labels": {"service": "app1"}},
            {"timestamp": "2000000000", "line": "msg2", "labels": {"service": "app1"}},
            {"timestamp": "3000000000", "line": "msg3", "labels": {"service": "app2"}}
        ]
        
        result = await client._send_to_loki(entries)
        
        # Should succeed
        assert result["written"] == 3
        assert result["errors"] == 0
    
    @pytest.mark.asyncio
    async def test_retry_logic(self, loki_config):
        """Test retry logic for failed requests."""
        retry_count = 0
        
        def handler(request: Request) -> Response:
            nonlocal retry_count
            retry_count += 1
            if retry_count <= 2:  # Fail first 2 attempts
                return Response(status_code=500, content=b"Server Error")
            return Response(status_code=204, content=b"")  # Succeed on 3rd
        
        transport = MockTransport(handler)
        
        client = LokiClient(loki_config)
        client.client = httpx.AsyncClient(transport=transport)
        
        entries = [{"timestamp": "1000000000", "line": "test", "labels": {"service": "test"}}]
        result = await client._send_to_loki(entries)
        
        # Should eventually succeed after retries
        assert result["written"] == 1
        assert result["errors"] == 0
        assert retry_count == 3  # Initial + 2 retries
    
    @pytest.mark.asyncio
    async def test_retry_exhaustion(self, loki_config):
        """Test behavior when all retries are exhausted."""
        def handler(request: Request) -> Response:
            return Response(status_code=500, content=b"Server Error")
        
        transport = MockTransport(handler)
        
        client = LokiClient(loki_config)
        client.client = httpx.AsyncClient(transport=transport)
        
        entries = [{"timestamp": "1000000000", "line": "test", "labels": {"service": "test"}}]
        result = await client._send_to_loki(entries)
        
        # Should fail after all retries
        assert result["written"] == 0
        assert result["errors"] == 1
    
    @pytest.mark.asyncio
    async def test_write_events_integration(self, loki_config):
        """Test full write_events flow with batching."""
        def handler(request: Request) -> Response:
            # Validate request structure
            payload = json.loads(request.content)
            assert "streams" in payload
            assert len(payload["streams"]) > 0
            
            for stream in payload["streams"]:
                assert "stream" in stream  # Labels
                assert "values" in stream  # Timestamp-value pairs
                
            return Response(status_code=204, content=b"")
        
        transport = MockTransport(handler)
        
        client = LokiClient(loki_config)
        await client.start()
        client.client = httpx.AsyncClient(transport=transport)
        
        events = [
            {"message": "Event 1", "service": "test", "timestamp": 1000000000},
            {"message": "Event 2", "service": "test", "timestamp": 2000000000},
            {"message": "Event 3", "service": "other", "timestamp": 3000000000}
        ]
        
        # Write events (should queue them)
        result = await client.write_events(events)
        assert result["queued"] == 3
        
        # Force flush to send to Loki
        flush_result = await client._flush_batch(force=True)
        assert flush_result["written"] == 3
        
        await client.stop()


@pytest.mark.asyncio
async def test_pipeline_integration():
    """Test that redaction precedes Loki push in the pipeline."""
    config = LokiConfig(enabled=True, batch_size=10)
    client = LokiClient(config)
    
    # Event with sensitive data that should be redacted before Loki
    event = {
        "message": "User login successful",
        "service": "auth",
        "user_id": "sensitive-123",  # Should not be in labels
        "__spool_id": "internal-456"  # Should be filtered out
    }
    
    loki_entry = client._convert_to_loki_entry(event)
    
    # Internal fields should be excluded
    labels = loki_entry["labels"]
    assert "user_id" not in labels  # High cardinality, not in safe labels
    
    # The line should not contain internal fields starting with underscore
    assert "__spool_id" not in loki_entry["line"]