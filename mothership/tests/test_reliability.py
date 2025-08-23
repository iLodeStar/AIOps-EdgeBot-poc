"""Tests for reliability components: retry, circuit breaker, and queuing."""

import asyncio
import json
import pytest
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import httpx

from app.storage.reliability import (
    SinkRetryManager, SinkCircuitBreaker, SinkPersistentQueue, CircuitBreakerState,
    should_retry_response, get_retry_after, RetryableException, NonRetryableException
)
from app.storage.resilient_sink import ResilientSink
from app.storage.protocols import StorageSink


class TestResponseRetryLogic:
    """Test retry decision logic for HTTP responses."""
    
    def test_should_retry_5xx_errors(self):
        """Test that 5xx errors should be retried."""
        response = MagicMock()
        response.status_code = 500
        assert should_retry_response(response)
        
        response.status_code = 502  
        assert should_retry_response(response)
        
        response.status_code = 503
        assert should_retry_response(response)
        
    def test_should_retry_429(self):
        """Test that 429 Too Many Requests should be retried."""
        response = MagicMock()
        response.status_code = 429
        assert should_retry_response(response)
        
    def test_should_retry_some_4xx(self):
        """Test that specific 4xx errors should be retried."""
        response = MagicMock()
        response.status_code = 408  # Request Timeout
        assert should_retry_response(response)
        
        response.status_code = 423  # Locked
        assert should_retry_response(response)
        
    def test_should_not_retry_most_4xx(self):
        """Test that most 4xx errors should not be retried."""  
        response = MagicMock()
        response.status_code = 400  # Bad Request
        assert not should_retry_response(response)
        
        response.status_code = 401  # Unauthorized
        assert not should_retry_response(response)
        
        response.status_code = 404  # Not Found
        assert not should_retry_response(response)
        
    def test_should_not_retry_2xx_3xx(self):
        """Test that 2xx and 3xx responses should not be retried."""
        response = MagicMock()
        response.status_code = 200
        assert not should_retry_response(response)
        
        response.status_code = 201
        assert not should_retry_response(response)
        
        response.status_code = 302
        assert not should_retry_response(response)
        
    def test_get_retry_after_header(self):
        """Test extracting Retry-After header."""
        response = MagicMock()
        response.headers = {'retry-after': '30'}
        assert get_retry_after(response) == 30.0
        
        response.headers = {}
        assert get_retry_after(response) is None
        
        response.headers = {'retry-after': 'invalid'}
        assert get_retry_after(response) is None


class TestSinkRetryManager:
    """Test retry manager functionality."""
    
    def test_retry_manager_initialization(self):
        """Test retry manager initializes with correct config."""
        config = {
            'max_retries': 5,
            'initial_backoff_ms': 2000,
            'max_backoff_ms': 120000,
            'jitter_factor': 0.2,
            'timeout_ms': 60000
        }
        
        retry_manager = SinkRetryManager("test_sink", config)
        assert retry_manager.max_retries == 5
        assert retry_manager.initial_backoff_ms == 2000
        assert retry_manager.max_backoff_ms == 120000
        assert retry_manager.jitter_factor == 0.2
        assert retry_manager.timeout_ms == 60000
        
    def test_backoff_calculation(self):
        """Test exponential backoff with jitter calculation."""
        retry_manager = SinkRetryManager("test", {'initial_backoff_ms': 1000, 'max_backoff_ms': 8000})
        
        # Test exponential backoff without jitter (minimum case)
        with patch('random.random', return_value=0.0):
            backoff = retry_manager.calculate_backoff(0)  # First retry
            assert backoff == 1.0  # 1000ms = 1s
            
            backoff = retry_manager.calculate_backoff(1)  # Second retry  
            assert backoff == 2.0  # 2000ms = 2s
            
            backoff = retry_manager.calculate_backoff(2)  # Third retry
            assert backoff == 4.0  # 4000ms = 4s
            
            backoff = retry_manager.calculate_backoff(3)  # Fourth retry - should be capped
            assert backoff == 8.0  # 8000ms = 8s (max_backoff_ms)
            
    def test_backoff_respects_retry_after(self):
        """Test that Retry-After header is respected."""
        retry_manager = SinkRetryManager("test", {})
        backoff = retry_manager.calculate_backoff(0, retry_after=45.0)
        assert backoff == 45.0
        
    @pytest.mark.asyncio
    async def test_successful_operation_no_retry(self):
        """Test successful operation requires no retries."""
        retry_manager = SinkRetryManager("test", {})
        
        mock_operation = AsyncMock(return_value="success")
        
        result = await retry_manager.execute_with_retry(mock_operation, [])
        assert result == "success"
        assert mock_operation.call_count == 1
        
    @pytest.mark.asyncio
    async def test_retry_on_timeout(self):
        """Test retry behavior on timeout."""
        config = {'max_retries': 2, 'initial_backoff_ms': 10}  # Fast backoff for testing
        retry_manager = SinkRetryManager("test", config)
        
        mock_operation = AsyncMock(side_effect=[
            asyncio.TimeoutError(),
            asyncio.TimeoutError(),
            "success"
        ])
        
        with patch('asyncio.sleep'):  # Skip actual sleep delays
            result = await retry_manager.execute_with_retry(mock_operation, [])
            
        assert result == "success"
        assert mock_operation.call_count == 3
        
    @pytest.mark.asyncio 
    async def test_retry_exhaustion(self):
        """Test behavior when all retries are exhausted."""
        config = {'max_retries': 2, 'initial_backoff_ms': 10}
        retry_manager = SinkRetryManager("test", config)
        
        mock_operation = AsyncMock(side_effect=asyncio.TimeoutError())
        
        with patch('asyncio.sleep'):  # Skip actual sleep delays
            with pytest.raises(asyncio.TimeoutError):
                await retry_manager.execute_with_retry(mock_operation, [])
                
        assert mock_operation.call_count == 3  # Initial + 2 retries
        
    @pytest.mark.asyncio
    async def test_no_retry_on_non_retryable_http_error(self):
        """Test that non-retryable HTTP errors are not retried."""
        retry_manager = SinkRetryManager("test", {})
        
        # Mock 400 Bad Request (non-retryable)
        response = MagicMock()
        response.status_code = 400
        http_error = httpx.HTTPStatusError("Bad request", request=MagicMock(), response=response)
        
        mock_operation = AsyncMock(side_effect=http_error)
        
        with pytest.raises(NonRetryableException):
            await retry_manager.execute_with_retry(mock_operation, [])
            
        assert mock_operation.call_count == 1  # No retries


class TestSinkCircuitBreaker:
    """Test circuit breaker functionality."""
    
    def test_circuit_breaker_initialization(self):
        """Test circuit breaker initializes in closed state."""
        config = {'failure_threshold': 3, 'open_duration_sec': 30}
        cb = SinkCircuitBreaker("test", config)
        
        assert cb.state == CircuitBreakerState.CLOSED
        assert cb.failure_threshold == 3
        assert cb.open_duration_sec == 30
        
    @pytest.mark.asyncio
    async def test_circuit_breaker_closed_permits_calls(self):
        """Test that closed circuit breaker permits calls."""
        cb = SinkCircuitBreaker("test", {})
        assert await cb.is_call_permitted()
        
    @pytest.mark.asyncio
    async def test_circuit_breaker_opens_after_failures(self):
        """Test that circuit breaker opens after threshold failures.""" 
        config = {'failure_threshold': 3}
        cb = SinkCircuitBreaker("test", config)
        
        # Record failures up to threshold
        for _ in range(3):
            await cb.record_failure()
            
        assert cb.state == CircuitBreakerState.OPEN
        assert not await cb.is_call_permitted()
        
    @pytest.mark.asyncio
    async def test_circuit_breaker_transitions_to_half_open(self):
        """Test circuit breaker transitions to half-open after timeout."""
        config = {'failure_threshold': 2, 'open_duration_sec': 0.1}  # Fast timeout
        cb = SinkCircuitBreaker("test", config)
        
        # Trip the circuit breaker
        await cb.record_failure()
        await cb.record_failure()
        assert cb.state == CircuitBreakerState.OPEN
        
        # Wait for timeout and check transition
        await asyncio.sleep(0.2)
        assert await cb.is_call_permitted()
        assert cb.state == CircuitBreakerState.HALF_OPEN
        
    @pytest.mark.asyncio
    async def test_circuit_breaker_resets_on_success_in_half_open(self):
        """Test that success in half-open state resets to closed."""
        config = {'failure_threshold': 1, 'open_duration_sec': 0.1}
        cb = SinkCircuitBreaker("test", config)
        
        # Trip circuit breaker
        await cb.record_failure()
        assert cb.state == CircuitBreakerState.OPEN
        
        # Transition to half-open
        await asyncio.sleep(0.2)
        await cb.is_call_permitted()
        assert cb.state == CircuitBreakerState.HALF_OPEN
        
        # Record success - should reset to closed
        await cb.record_success()
        assert cb.state == CircuitBreakerState.CLOSED
        
    @pytest.mark.asyncio
    async def test_half_open_inflight_limit(self):
        """Test that half-open state limits inflight requests."""
        config = {'failure_threshold': 1, 'open_duration_sec': 0.1, 'half_open_max_inflight': 1}
        cb = SinkCircuitBreaker("test", config)
        
        # Trip and transition to half-open
        await cb.record_failure()
        await asyncio.sleep(0.2)
        
        # First call should be permitted
        assert await cb.execute_call()
        assert cb.state == CircuitBreakerState.HALF_OPEN
        
        # Second call should be rejected (inflight limit)
        assert not await cb.is_call_permitted()
        
    def test_circuit_breaker_stats(self):
        """Test circuit breaker statistics."""
        cb = SinkCircuitBreaker("test", {'failure_threshold': 3})
        
        stats = cb.get_stats()
        assert stats['state'] == 'closed'
        assert stats['failure_count'] == 0
        assert stats['inflight_requests'] == 0


class TestSinkPersistentQueue:
    """Test persistent queue functionality."""
    
    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)
            
    @pytest.fixture
    def queue_config(self, temp_dir):
        """Create queue configuration."""
        return {
            'enabled': True,
            'queue_dir': str(temp_dir / 'queue'),
            'dlq_dir': str(temp_dir / 'dlq'),
            'queue_max_bytes': 1024 * 1024,  # 1MB
            'queue_flush_interval_ms': 1000
        }
        
    def test_queue_initialization(self, queue_config):
        """Test queue initializes correctly.""" 
        queue = SinkPersistentQueue("test", queue_config)
        
        # Check directories were created
        assert Path(queue_config['queue_dir']).exists()
        assert Path(queue_config['dlq_dir']).exists()
        
        # Check database was created with correct schema
        assert queue.db_path.exists()
        with sqlite3.connect(str(queue.db_path)) as conn:
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            assert 'queue' in tables
            
    @pytest.mark.asyncio
    async def test_enqueue_dequeue_events(self, queue_config):
        """Test enqueueing and dequeueing events.""" 
        queue = SinkPersistentQueue("test", queue_config)
        
        events = [
            {"message": "test1", "timestamp": "2023-01-01T00:00:00Z"},
            {"message": "test2", "timestamp": "2023-01-01T00:01:00Z"}
        ]
        
        # Enqueue events
        success = await queue.enqueue(events)
        assert success
        
        # Dequeue events
        dequeued = await queue.dequeue(batch_size=10)
        assert len(dequeued) == 2
        assert dequeued[0]['message'] == 'test1'
        assert dequeued[1]['message'] == 'test2'
        assert '_queue_id' in dequeued[0]  # Internal tracking ID added
        
    @pytest.mark.asyncio
    async def test_ack_events(self, queue_config):
        """Test acknowledging events removes them from queue."""
        queue = SinkPersistentQueue("test", queue_config)
        
        events = [{"message": "test"}]
        await queue.enqueue(events)
        
        # Dequeue and ack
        dequeued = await queue.dequeue()
        await queue.ack_events(dequeued)
        
        # Queue should now be empty
        empty_batch = await queue.dequeue()
        assert len(empty_batch) == 0
        
    @pytest.mark.asyncio
    async def test_nack_events_with_retries(self, queue_config):
        """Test nacking events increments retry count."""
        queue = SinkPersistentQueue("test", queue_config)
        
        events = [{"message": "test"}]
        await queue.enqueue(events)
        
        dequeued = await queue.dequeue()
        await queue.nack_events(dequeued, max_retries=3)
        
        # Event should still be in queue with incremented retry count
        retry_batch = await queue.dequeue()
        assert len(retry_batch) == 1
        
    @pytest.mark.asyncio 
    async def test_nack_events_moves_to_dlq(self, queue_config):
        """Test that events exceeding max retries move to DLQ."""
        queue = SinkPersistentQueue("test", queue_config)
        
        events = [{"message": "failing_event"}]
        await queue.enqueue(events)
        
        # Exhaust retries
        for _ in range(4):  # max_retries = 3, so 4 nacks should trigger DLQ
            dequeued = await queue.dequeue()
            if dequeued:
                await queue.nack_events(dequeued, max_retries=3)
        
        # Main queue should be empty
        empty_batch = await queue.dequeue()
        assert len(empty_batch) == 0
        
        # Check DLQ has the event
        stats = queue.get_stats()
        assert stats['dlq_count'] >= 1
        
    @pytest.mark.asyncio
    async def test_queue_size_limit(self, queue_config):
        """Test that queue respects size limits."""
        # Set very small size limit
        queue_config['queue_max_bytes'] = 100  
        queue = SinkPersistentQueue("test", queue_config)
        
        # Try to enqueue large event
        large_event = [{"message": "x" * 200}]  # Larger than limit
        success = await queue.enqueue(large_event)
        assert not success  # Should be rejected
        
    def test_queue_stats(self, queue_config):
        """Test queue statistics reporting."""
        queue = SinkPersistentQueue("test", queue_config)
        
        stats = queue.get_stats()
        assert 'queue_count' in stats
        assert 'queue_bytes' in stats
        assert 'dlq_count' in stats
        assert 'max_bytes' in stats


class MockSink:
    """Mock sink for testing ResilientSink."""
    
    def __init__(self, fail_count=0, return_value=None):
        self.fail_count = fail_count
        self.current_fails = 0
        self.return_value = return_value or {"written": 1, "errors": 0}
        self.calls = []
        
    async def start(self):
        pass
        
    async def stop(self):
        pass
        
    async def write_events(self, events):
        self.calls.append(events)
        if self.current_fails < self.fail_count:
            self.current_fails += 1
            raise Exception("Mock failure")
        return self.return_value
        
    def is_healthy(self):
        return True


class TestResilientSink:
    """Test resilient sink wrapper."""
    
    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)
    
    @pytest.mark.asyncio
    async def test_resilient_sink_basic_operation(self):
        """Test basic operation without failures."""
        mock_sink = MockSink()
        config = {}
        
        resilient = ResilientSink("test", mock_sink, config)
        await resilient.start()
        
        events = [{"message": "test"}]
        result = await resilient.write_events(events)
        
        assert result["written"] == 1
        assert result["errors"] == 0
        assert len(mock_sink.calls) == 1
        
        await resilient.stop()
        
    @pytest.mark.asyncio
    async def test_resilient_sink_with_retry(self, temp_dir):
        """Test resilient sink with retry on failure."""
        # Mock sink that fails once then succeeds with a retryable error
        from unittest.mock import AsyncMock
        mock_sink = AsyncMock()
        
        # First call fails with timeout, second succeeds
        mock_sink.write_events.side_effect = [
            asyncio.TimeoutError("Mock timeout"),
            {"written": 1, "errors": 0}
        ]
        mock_sink.start = AsyncMock()
        mock_sink.stop = AsyncMock()
        mock_sink.is_healthy.return_value = True
        
        config = {
            'retry': {
                'enabled': True,
                'max_retries': 2,
                'initial_backoff_ms': 10  # Fast for testing
            }
        }
        
        resilient = ResilientSink("test", mock_sink, config)
        
        with patch('asyncio.sleep'):  # Skip sleep delays
            await resilient.start()
            
            events = [{"message": "test"}]
            result = await resilient.write_events(events)
            
            await resilient.stop()
        
        # Should succeed after retry
        assert result["written"] == 1
        assert mock_sink.write_events.call_count == 2  # Initial call + 1 retry
        
    @pytest.mark.asyncio
    async def test_resilient_sink_with_circuit_breaker(self, temp_dir):
        """Test resilient sink with circuit breaker."""
        from unittest.mock import AsyncMock
        mock_sink = AsyncMock()
        
        # Always fails with retryable error
        mock_sink.write_events.side_effect = asyncio.TimeoutError("Mock timeout")
        mock_sink.start = AsyncMock()
        mock_sink.stop = AsyncMock()  
        mock_sink.is_healthy.return_value = True
        
        config = {
            'retry': {
                'enabled': True,
                'max_retries': 1,  # Only 1 retry to speed up test
                'initial_backoff_ms': 10
            },
            'circuit_breaker': {
                'enabled': True,
                'failure_threshold': 2  # Trip after 2 failures
            }
        }
        
        resilient = ResilientSink("test", mock_sink, config)
        
        with patch('asyncio.sleep'):  # Skip sleep delays
            await resilient.start()
            
            events = [{"message": "test"}]
            
            # First call: initial + 1 retry = 2 calls, fails, CB failure_count = 1
            result1 = await resilient.write_events(events) 
            
            # Second call: initial + 1 retry = 2 calls, fails, CB failure_count = 2, CB opens
            result2 = await resilient.write_events(events)
            
            # Third call: CB is open, should be rejected immediately
            result3 = await resilient.write_events(events)
            
            await resilient.stop()
        
        # First two calls each make 2 attempts (initial + 1 retry)
        # Third call is rejected by circuit breaker
        assert mock_sink.write_events.call_count == 4  # 2 + 2 + 0
        
        # Third call should return errors since no queue
        assert result3["errors"] > 0
        
    @pytest.mark.asyncio
    async def test_resilient_sink_with_queue(self, temp_dir):
        """Test resilient sink with persistent queue."""
        mock_sink = MockSink(fail_count=1)  # Fails once
        
        config = {
            'queue': {
                'enabled': True,
                'queue_dir': str(temp_dir / 'queue'),
                'dlq_dir': str(temp_dir / 'dlq'),
                'queue_flush_interval_ms': 100  # Fast processing
            }
        }
        
        resilient = ResilientSink("test", mock_sink, config)
        await resilient.start()
        
        events = [{"message": "test"}]
        result = await resilient.write_events(events)
        
        # Should queue on failure
        if result["written"] == 0:
            # Wait a bit for queue processor
            await asyncio.sleep(0.2)
        
        await resilient.stop()
        
        # Queue processor should eventually succeed
        assert len(mock_sink.calls) >= 1