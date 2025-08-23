"""Tests for reliability components: retries, circuit breakers, persistent queue."""

import asyncio
import json
import tempfile
import time
from pathlib import Path
from typing import Dict, Any, List
from unittest.mock import Mock, AsyncMock
import pytest
import httpx
from httpx import Request, Response

from mothership.app.storage.reliability import (
    SinkRetryManager, SinkCircuitBreaker, PersistentQueue, IdempotencyManager,
    RetryConfig, CircuitBreakerConfig, CircuitState
)


class TestSinkRetryManager:
    """Test retry manager functionality."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.config = RetryConfig(
            max_retries=3,
            initial_backoff_ms=100,
            max_backoff_ms=1000,
            jitter_factor=0.1,
            timeout_ms=5000
        )
        self.retry_manager = SinkRetryManager("test_sink", self.config)
    
    def test_should_retry_on_timeout(self):
        """Test retry on timeout exceptions."""
        exception = httpx.TimeoutException("Request timed out")
        
        assert self.retry_manager.should_retry(exception=exception, attempt=1)
        assert self.retry_manager.should_retry(exception=exception, attempt=2)
        assert self.retry_manager.should_retry(exception=exception, attempt=3)
        assert not self.retry_manager.should_retry(exception=exception, attempt=4)
    
    def test_should_retry_on_5xx(self):
        """Test retry on 5xx HTTP status codes."""
        response = Mock(spec=httpx.Response)
        response.status_code = 500
        
        assert self.retry_manager.should_retry(response=response, attempt=1)
        
        response.status_code = 502
        assert self.retry_manager.should_retry(response=response, attempt=1)
        
        response.status_code = 503
        assert self.retry_manager.should_retry(response=response, attempt=1)
    
    def test_should_retry_on_429(self):
        """Test retry on rate limiting (429)."""
        response = Mock(spec=httpx.Response)
        response.status_code = 429
        
        assert self.retry_manager.should_retry(response=response, attempt=1)
    
    def test_should_not_retry_on_4xx(self):
        """Test no retry on client errors (except 429)."""
        response = Mock(spec=httpx.Response)
        
        for status_code in [400, 401, 403, 404, 422]:
            response.status_code = status_code
            assert not self.retry_manager.should_retry(response=response, attempt=1)
    
    def test_backoff_delay_exponential(self):
        """Test exponential backoff calculation."""
        # First attempt should be around initial backoff
        delay1 = self.retry_manager.get_backoff_delay(1)
        assert 0.09 <= delay1 <= 0.12  # 100ms ± 10% jitter + conversion to seconds
        
        # Second attempt should be around 2x
        delay2 = self.retry_manager.get_backoff_delay(2)
        assert 0.18 <= delay2 <= 0.22  # ~200ms ± jitter
        
        # Third attempt should be around 4x  
        delay3 = self.retry_manager.get_backoff_delay(3)
        assert 0.36 <= delay3 <= 0.44  # ~400ms ± jitter
    
    def test_backoff_delay_honors_retry_after(self):
        """Test that Retry-After header is honored."""
        delay = self.retry_manager.get_backoff_delay(1, retry_after=5)
        assert delay == 5.0
        
        # Should still respect minimum
        delay = self.retry_manager.get_backoff_delay(1, retry_after=0)
        assert delay == 0.1
    
    def test_get_retry_after_header(self):
        """Test extraction of Retry-After header."""
        response = Mock(spec=httpx.Response)
        response.headers = {"retry-after": "30"}
        
        retry_after = self.retry_manager.get_retry_after(response)
        assert retry_after == 30
        
        # Invalid header
        response.headers = {"retry-after": "invalid"}
        retry_after = self.retry_manager.get_retry_after(response)
        assert retry_after is None
        
        # Missing header
        response.headers = {}
        retry_after = self.retry_manager.get_retry_after(response)
        assert retry_after is None


class TestSinkCircuitBreaker:
    """Test circuit breaker functionality."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.config = CircuitBreakerConfig(
            failure_threshold=3,
            open_duration_sec=1,
            half_open_max_inflight=2
        )
        self.circuit_breaker = SinkCircuitBreaker("test_sink", self.config)
    
    def test_initial_state_closed(self):
        """Test that circuit breaker starts in closed state."""
        assert self.circuit_breaker.get_state() == CircuitState.CLOSED
        assert self.circuit_breaker.can_execute()
    
    def test_transition_to_open_on_failures(self):
        """Test transition to open state after threshold failures."""
        # Record failures up to threshold
        for i in range(self.config.failure_threshold - 1):
            self.circuit_breaker.record_failure()
            assert self.circuit_breaker.get_state() == CircuitState.CLOSED
            assert self.circuit_breaker.can_execute()
        
        # One more failure should open the circuit
        self.circuit_breaker.record_failure()
        assert self.circuit_breaker.get_state() == CircuitState.OPEN
        assert not self.circuit_breaker.can_execute()
    
    def test_transition_to_half_open_after_timeout(self):
        """Test transition to half-open after timeout expires."""
        # Trip the circuit breaker
        for _ in range(self.config.failure_threshold):
            self.circuit_breaker.record_failure()
        
        assert self.circuit_breaker.get_state() == CircuitState.OPEN
        assert not self.circuit_breaker.can_execute()
        
        # Wait for timeout
        time.sleep(self.config.open_duration_sec + 0.1)
        
        # Should transition to half-open on next check
        assert self.circuit_breaker.can_execute()
        assert self.circuit_breaker.get_state() == CircuitState.HALF_OPEN
    
    def test_half_open_request_limiting(self):
        """Test request limiting in half-open state."""
        # Force to half-open state
        self.circuit_breaker.state = CircuitState.HALF_OPEN
        
        # Should allow up to max_inflight requests
        for i in range(self.config.half_open_max_inflight):
            assert self.circuit_breaker.can_execute()
            self.circuit_breaker.record_inflight()
        
        # Should not allow more
        assert not self.circuit_breaker.can_execute()
    
    def test_success_closes_from_half_open(self):
        """Test that success in half-open closes the circuit."""
        # Force to half-open state
        self.circuit_breaker.state = CircuitState.HALF_OPEN
        
        self.circuit_breaker.record_success()
        assert self.circuit_breaker.get_state() == CircuitState.CLOSED
    
    def test_failure_reopens_from_half_open(self):
        """Test that failure in half-open reopens the circuit."""
        # Force to half-open state
        self.circuit_breaker.state = CircuitState.HALF_OPEN
        
        self.circuit_breaker.record_failure()
        assert self.circuit_breaker.get_state() == CircuitState.OPEN


class TestPersistentQueue:
    """Test persistent queue functionality."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.queue_dir = Path(self.temp_dir) / "queue"
        self.dlq_dir = Path(self.temp_dir) / "dlq"
        
        self.queue = PersistentQueue(
            queue_dir=str(self.queue_dir),
            max_bytes=1024 * 1024,  # 1 MB
            flush_interval_ms=1000,
            dlq_dir=str(self.dlq_dir),
            flush_bandwidth_bytes_per_sec=1024 * 1024
        )
    
    @pytest.mark.asyncio
    async def test_enqueue_and_dequeue(self):
        """Test basic enqueue and dequeue operations."""
        events = [
            {"message": "Event 1", "timestamp": time.time()},
            {"message": "Event 2", "timestamp": time.time()}
        ]
        
        # Enqueue events
        success = await self.queue.enqueue(events, "test_sink")
        assert success
        
        # Dequeue events
        batch = await self.queue.dequeue_batch(10)
        assert len(batch) == 1
        
        filename, dequeued_events, sink_name = batch[0]
        assert dequeued_events == events
        assert sink_name == "test_sink"
        
        # Commit batch
        await self.queue.commit_batch([filename])
        
        # Should be empty now
        batch = await self.queue.dequeue_batch(10)
        assert len(batch) == 0
    
    @pytest.mark.asyncio
    async def test_queue_size_limit(self):
        """Test that queue respects size limits."""
        # Create a large event that exceeds the queue size
        large_event = [{"message": "x" * (2 * 1024 * 1024), "timestamp": time.time()}]  # 2 MB
        
        # Should fail to enqueue
        success = await self.queue.enqueue(large_event, "test_sink")
        assert not success
    
    @pytest.mark.asyncio
    async def test_queue_persistence(self):
        """Test that queued events persist across restarts."""
        events = [{"message": "Persistent event", "timestamp": time.time()}]
        
        # Enqueue with first queue instance
        success = await self.queue.enqueue(events, "test_sink")
        assert success
        
        # Create new queue instance pointing to same directory
        new_queue = PersistentQueue(
            queue_dir=str(self.queue_dir),
            max_bytes=1024 * 1024,
            flush_interval_ms=1000,
            dlq_dir=str(self.dlq_dir),
            flush_bandwidth_bytes_per_sec=1024 * 1024
        )
        
        # Should be able to dequeue from new instance
        batch = await new_queue.dequeue_batch(10)
        assert len(batch) == 1
        assert batch[0][1] == events
    
    @pytest.mark.asyncio
    async def test_dlq_on_corrupt_file(self):
        """Test that corrupt files are moved to DLQ."""
        # Create a corrupt file
        corrupt_file = self.queue_dir / "corrupt.json"
        self.queue_dir.mkdir(parents=True, exist_ok=True)
        corrupt_file.write_text("invalid json {")
        
        # Dequeue should move corrupt file to DLQ
        batch = await self.queue.dequeue_batch(10)
        assert len(batch) == 0
        
        # Check DLQ
        dlq_files = list(self.dlq_dir.glob("*.error"))
        assert len(dlq_files) == 1
    
    def test_get_stats(self):
        """Test queue statistics."""
        stats = self.queue.get_stats()
        
        assert "current_bytes" in stats
        assert "max_bytes" in stats
        assert "utilization" in stats
        assert "file_count" in stats
        assert "dlq_count" in stats


class TestIdempotencyManager:
    """Test idempotency manager functionality."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.idempotency = IdempotencyManager(window_sec=5)  # Short window for testing
    
    @pytest.mark.asyncio
    async def test_duplicate_detection(self):
        """Test that duplicate batches are detected."""
        events = [
            {"message": "Event 1", "timestamp": time.time()},
            {"message": "Event 2", "timestamp": time.time()}
        ]
        
        # First time should not be duplicate
        is_dup = await self.idempotency.is_duplicate(events)
        assert not is_dup
        
        # Same events should be duplicate
        is_dup = await self.idempotency.is_duplicate(events)
        assert is_dup
        
        # Different events should not be duplicate
        different_events = [{"message": "Different event"}]
        is_dup = await self.idempotency.is_duplicate(different_events)
        assert not is_dup
    
    @pytest.mark.asyncio
    async def test_window_expiry(self):
        """Test that old entries expire from the window."""
        events = [{"message": "Event", "timestamp": time.time()}]
        
        # Record events
        is_dup = await self.idempotency.is_duplicate(events)
        assert not is_dup
        
        # Should be duplicate immediately
        is_dup = await self.idempotency.is_duplicate(events)
        assert is_dup
        
        # Wait for window to expire
        time.sleep(6)
        
        # Should no longer be duplicate after expiry
        is_dup = await self.idempotency.is_duplicate(events)
        assert not is_dup
    
    def test_batch_key_generation(self):
        """Test that batch keys are deterministic."""
        events1 = [{"a": 1, "b": 2}, {"c": 3}]
        events2 = [{"b": 2, "a": 1}, {"c": 3}]  # Same data, different order
        events3 = [{"a": 1, "b": 2}, {"c": 4}]  # Different data
        
        key1 = self.idempotency._generate_batch_key(events1)
        key2 = self.idempotency._generate_batch_key(events2)
        key3 = self.idempotency._generate_batch_key(events3)
        
        assert key1 == key2  # Same content should produce same key
        assert key1 != key3  # Different content should produce different key
        assert len(key1) == 16  # Key should be 16 hex chars


@pytest.fixture
def loki_config():
    """Fixture providing Loki configuration for testing."""
    return {
        'enabled': True,
        'url': 'http://localhost:3100',
        'batch_size': 10,
        'batch_timeout_seconds': 1.0
    }


class MockSink:
    """Mock sink for testing reliability wrapper."""
    
    def __init__(self, should_fail=False, status_code=200):
        self.should_fail = should_fail
        self.status_code = status_code
        self.call_count = 0
        
    async def start(self):
        pass
        
    async def stop(self):
        pass
        
    async def write_events(self, events):
        self.call_count += 1
        
        if self.should_fail:
            if self.status_code >= 500:
                # Simulate server error
                response = Mock(spec=httpx.Response)
                response.status_code = self.status_code
                raise httpx.HTTPStatusError("Server error", request=None, response=response)
            else:
                # Simulate timeout
                raise httpx.TimeoutException("Timeout")
                
        return {"written": len(events), "errors": 0}
        
    def is_healthy(self):
        return not self.should_fail


class TestReliableSinkWrapper:
    """Test the reliable sink wrapper integration."""
    
    @pytest.mark.asyncio
    async def test_retry_on_failure(self):
        """Test that wrapper retries on failures."""
        mock_sink = MockSink(should_fail=True)
        
        config = {
            'reliability': {
                'max_retries': 2,
                'initial_backoff_ms': 10,  # Fast for testing
                'max_backoff_ms': 100,
                'jitter_factor': 0.0  # No jitter for predictable testing
            }
        }
        
        from mothership.app.storage.sinks import ReliableSinkWrapper
        wrapper = ReliableSinkWrapper("test", mock_sink, config)
        
        events = [{"message": "test"}]
        result = await wrapper.write_events(events)
        
        # Should have retried max_retries + 1 times (initial + retries)
        assert mock_sink.call_count == 3
        assert result["errors"] == 1
        assert result["written"] == 0
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_integration(self):
        """Test that circuit breaker prevents calls when open."""
        mock_sink = MockSink(should_fail=True)
        
        config = {
            'reliability': {
                'max_retries': 0,  # No retries to trigger circuit breaker faster
                'failure_threshold': 2,
                'open_duration_sec': 1
            }
        }
        
        from mothership.app.storage.sinks import ReliableSinkWrapper
        wrapper = ReliableSinkWrapper("test", mock_sink, config)
        
        events = [{"message": "test"}]
        
        # First failure
        result1 = await wrapper.write_events(events)
        assert result1["written"] == 0
        
        # Second failure should open circuit
        result2 = await wrapper.write_events(events)
        assert result2["written"] == 0
        
        # Circuit should now be open, call should be blocked
        result3 = await wrapper.write_events(events)
        assert "circuit_open" in result3
        
        # Should have only 2 calls to sink (circuit blocked the third)
        assert mock_sink.call_count == 2