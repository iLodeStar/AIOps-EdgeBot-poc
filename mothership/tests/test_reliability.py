"""Tests for reliability components (circuit breaker, retry, idempotency)."""
import asyncio
import pytest
import time
from unittest.mock import AsyncMock, Mock, MagicMock
import httpx

from app.reliability import CircuitBreaker, RetryManager, IdempotencyManager, CircuitState


class TestCircuitBreaker:
    """Test circuit breaker functionality."""
    
    def test_circuit_breaker_initialization(self):
        """Test circuit breaker starts in closed state."""
        config = {
            'failure_threshold': 3,
            'open_duration_sec': 60,
            'half_open_max_inflight': 1
        }
        cb = CircuitBreaker("test_sink", config)
        
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0
        assert cb.can_execute() is True
    
    def test_circuit_breaker_trips_on_failures(self):
        """Test circuit breaker opens after failure threshold."""
        config = {
            'failure_threshold': 2,
            'open_duration_sec': 60,
            'half_open_max_inflight': 1
        }
        cb = CircuitBreaker("test_sink", config)
        
        # Record failures
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED
        assert cb.can_execute() is True
        
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.can_execute() is False
    
    def test_circuit_breaker_half_open_transition(self):
        """Test circuit breaker transitions to half-open after timeout."""
        config = {
            'failure_threshold': 1,
            'open_duration_sec': 0.1,  # Very short timeout for testing
            'half_open_max_inflight': 1
        }
        cb = CircuitBreaker("test_sink", config)
        
        # Trip the circuit
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.can_execute() is False
        
        # Wait for timeout
        time.sleep(0.2)
        
        # Should transition to half-open on next execution check
        assert cb.can_execute() is True
        assert cb.state == CircuitState.HALF_OPEN
    
    def test_circuit_breaker_success_resets(self):
        """Test successful operation resets circuit breaker."""
        config = {
            'failure_threshold': 1,
            'open_duration_sec': 0.1,
            'half_open_max_inflight': 1
        }
        cb = CircuitBreaker("test_sink", config)
        
        # Trip circuit and transition to half-open
        cb.record_failure()
        time.sleep(0.2)
        cb.can_execute()  # Transition to half-open
        
        assert cb.state == CircuitState.HALF_OPEN
        
        # Record success should reset to closed
        cb.record_success()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0
    
    def test_circuit_breaker_timeout_handling(self):
        """Test timeout is treated as failure."""
        config = {'failure_threshold': 1, 'open_duration_sec': 60, 'half_open_max_inflight': 1}
        cb = CircuitBreaker("test_sink", config)
        
        cb.record_timeout()
        assert cb.state == CircuitState.OPEN
        assert cb.failure_count == 1


class TestRetryManager:
    """Test retry manager with jittered exponential backoff."""
    
    def test_retry_manager_initialization(self):
        """Test retry manager initializes with correct defaults."""
        config = {
            'max_retries': 3,
            'initial_backoff_ms': 100,
            'max_backoff_ms': 5000,
            'jitter_factor': 0.1
        }
        rm = RetryManager("test_sink", config)
        
        assert rm.max_retries == 3
        assert rm.initial_backoff_ms == 100
        assert rm.max_backoff_ms == 5000
        assert rm.jitter_factor == 0.1
    
    def test_should_retry_logic(self):
        """Test retry decision based on exception type."""
        config = {'max_retries': 3, 'initial_backoff_ms': 100, 'max_backoff_ms': 5000}
        rm = RetryManager("test_sink", config)
        
        # Should retry on attempt 0 for any exception
        assert rm.should_retry(0, Exception("test")) is True
        
        # Should not retry after max attempts
        assert rm.should_retry(5, Exception("test")) is False
        
        # Test with HTTP status codes
        mock_response = Mock()
        mock_response.status_code = 500
        mock_exception = Mock()
        mock_exception.response = mock_response
        
        assert rm.should_retry(0, mock_exception) is True
        
        # 4xx should not retry (except 429)
        mock_response.status_code = 404
        assert rm.should_retry(0, mock_exception) is False
        
        # 429 should retry
        mock_response.status_code = 429
        assert rm.should_retry(0, mock_exception) is True
    
    def test_backoff_calculation(self):
        """Test exponential backoff with jitter."""
        config = {
            'max_retries': 5,
            'initial_backoff_ms': 1000,
            'max_backoff_ms': 10000,
            'jitter_factor': 0.0  # No jitter for predictable testing
        }
        rm = RetryManager("test_sink", config)
        
        # First attempt: 1000ms
        backoff1 = rm.calculate_backoff(0)
        assert backoff1 == 1.0
        
        # Second attempt: 2000ms
        backoff2 = rm.calculate_backoff(1)
        assert backoff2 == 2.0
        
        # Third attempt: 4000ms
        backoff3 = rm.calculate_backoff(2)
        assert backoff3 == 4.0
        
        # Should cap at max_backoff_ms
        backoff_max = rm.calculate_backoff(10)
        assert backoff_max == 10.0
    
    def test_retry_after_header_parsing(self):
        """Test Retry-After header parsing."""
        config = {'max_retries': 3, 'initial_backoff_ms': 100, 'max_backoff_ms': 5000}
        rm = RetryManager("test_sink", config)
        
        # Valid numeric retry-after
        headers = {"Retry-After": "30"}
        assert rm.get_retry_after_delay(headers) == 30.0
        
        # Case insensitive
        headers = {"retry-after": "15"}
        assert rm.get_retry_after_delay(headers) == 15.0
        
        # No header
        assert rm.get_retry_after_delay({}) is None
        
        # Invalid format
        assert rm.get_retry_after_delay({"Retry-After": "invalid"}) is None
    
    @pytest.mark.asyncio
    async def test_execute_with_retry_success(self):
        """Test successful operation without retries."""
        config = {'max_retries': 3, 'initial_backoff_ms': 10, 'max_backoff_ms': 1000}
        rm = RetryManager("test_sink", config)
        
        mock_operation = AsyncMock(return_value="success")
        
        result = await rm.execute_with_retry(mock_operation, "arg1", kwarg1="value1")
        
        assert result == "success"
        assert mock_operation.call_count == 1
        mock_operation.assert_called_with("arg1", kwarg1="value1")
    
    @pytest.mark.asyncio
    async def test_execute_with_retry_failure_then_success(self):
        """Test operation that fails then succeeds."""
        config = {'max_retries': 3, 'initial_backoff_ms': 10, 'max_backoff_ms': 1000, 'jitter_factor': 0}
        rm = RetryManager("test_sink", config)
        
        # Mock operation that fails twice then succeeds
        mock_operation = AsyncMock(side_effect=[Exception("fail"), Exception("fail"), "success"])
        
        result = await rm.execute_with_retry(mock_operation)
        
        assert result == "success"
        assert mock_operation.call_count == 3
    
    @pytest.mark.asyncio
    async def test_execute_with_retry_max_attempts_exceeded(self):
        """Test operation that exceeds max retry attempts."""
        config = {'max_retries': 2, 'initial_backoff_ms': 10, 'max_backoff_ms': 1000, 'jitter_factor': 0}
        rm = RetryManager("test_sink", config)
        
        mock_operation = AsyncMock(side_effect=Exception("always fails"))
        
        with pytest.raises(Exception, match="always fails"):
            await rm.execute_with_retry(mock_operation)
        
        assert mock_operation.call_count == 3  # Initial + 2 retries


class TestIdempotencyManager:
    """Test idempotency manager."""
    
    def test_idempotency_manager_initialization(self):
        """Test idempotency manager initialization."""
        config = {'window_sec': 1800}
        im = IdempotencyManager(config)
        
        assert im.window_sec == 1800
        assert len(im._seen_keys) == 0
    
    def test_generate_batch_key_deterministic(self):
        """Test batch key generation is deterministic."""
        config = {'window_sec': 3600}
        im = IdempotencyManager(config)
        
        batch1 = [{"message": "test1", "timestamp": "2023-01-01T00:00:00Z"}]
        batch2 = [{"message": "test1", "timestamp": "2023-01-01T00:00:00Z"}]
        
        key1 = im.generate_batch_key(batch1)
        key2 = im.generate_batch_key(batch2)
        
        assert key1 == key2
        assert isinstance(key1, str)
        assert len(key1) == 32  # MD5 hex digest
    
    def test_generate_batch_key_different_for_different_batches(self):
        """Test different batches generate different keys."""
        config = {'window_sec': 3600}
        im = IdempotencyManager(config)
        
        batch1 = [{"message": "test1", "timestamp": "2023-01-01T00:00:00Z"}]
        batch2 = [{"message": "test2", "timestamp": "2023-01-01T00:00:00Z"}]
        
        key1 = im.generate_batch_key(batch1)
        key2 = im.generate_batch_key(batch2)
        
        assert key1 != key2
    
    def test_duplicate_detection(self):
        """Test duplicate batch detection."""
        config = {'window_sec': 3600}
        im = IdempotencyManager(config)
        
        key = "test_key"
        
        # First time should not be duplicate
        assert im.is_duplicate(key) is False
        
        # Second time should be duplicate
        assert im.is_duplicate(key) is True
    
    def test_key_expiration(self):
        """Test expired keys are cleaned up."""
        config = {'window_sec': 0.1}  # Very short window for testing
        im = IdempotencyManager(config)
        
        key = "test_key"
        
        # Add key
        assert im.is_duplicate(key) is False
        assert len(im._seen_keys) == 1
        
        # Wait for expiration
        time.sleep(0.2)
        
        # Check key again - should trigger cleanup and not be duplicate
        assert im.is_duplicate("different_key") is False
        assert key not in im._seen_keys
    
    def test_get_stats(self):
        """Test statistics reporting."""
        config = {'window_sec': 1800}
        im = IdempotencyManager(config)
        
        im.is_duplicate("key1")
        im.is_duplicate("key2")
        
        stats = im.get_stats()
        
        assert stats['cached_keys'] == 2
        assert stats['window_sec'] == 1800


# Integration test with mocked httpx client
class TestReliabilityIntegration:
    """Test reliability components working together."""
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_with_retry_manager(self):
        """Test circuit breaker and retry manager integration."""
        cb_config = {'failure_threshold': 2, 'open_duration_sec': 0.1, 'half_open_max_inflight': 1}
        retry_config = {'max_retries': 3, 'initial_backoff_ms': 10, 'max_backoff_ms': 1000, 'jitter_factor': 0}
        
        cb = CircuitBreaker("test_sink", cb_config)
        rm = RetryManager("test_sink", retry_config)
        
        # Simulate operation that always fails
        async def failing_operation():
            cb.record_failure()
            raise Exception("Operation failed")
        
        # Should open circuit after threshold failures
        with pytest.raises(Exception):
            await rm.execute_with_retry(failing_operation)
        
        assert cb.state == CircuitState.OPEN
        assert cb.can_execute() is False
        
        # Wait for circuit to go half-open
        time.sleep(0.2)
        assert cb.can_execute() is True
        assert cb.state == CircuitState.HALF_OPEN
        
        # Successful operation should close circuit
        cb.record_success()
        assert cb.state == CircuitState.CLOSED