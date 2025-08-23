"""Tests for edge node reliability enhancements."""
import asyncio
import pytest
import time
import json
import tempfile
import os
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch
import httpx

import sys
sys.path.append('/home/runner/work/AIOps-EdgeBot-poc/AIOps-EdgeBot-poc/edge_node')

from app.output.shipper import RetryManager, IdempotencyManager
from app.output.queue import PersistentQueue, BandwidthLimiter, DLQManager


class TestEnhancedRetryManager:
    """Test enhanced retry manager for edge node."""
    
    def test_retry_manager_with_jitter(self):
        """Test retry manager with jittered exponential backoff."""
        rm = RetryManager(
            max_retries=3,
            initial_backoff_ms=1000,
            max_backoff_ms=10000,
            jitter_factor=0.2
        )
        
        assert rm.max_retries == 3
        assert rm.initial_backoff_ms == 1000
        assert rm.max_backoff_ms == 10000
        assert rm.jitter_factor == 0.2
    
    def test_add_failed_batch_with_retry_after(self):
        """Test adding failed batch with Retry-After header."""
        rm = RetryManager(max_retries=3, initial_backoff_ms=1000, max_backoff_ms=10000, jitter_factor=0)
        
        batch = [{"message": "test"}]
        headers = {"Retry-After": "30"}
        
        initial_time = time.time()
        rm.add_failed_batch(batch, headers)
        
        # Should have one retry batch scheduled
        assert len(rm._retry_batches) == 1
        batch_data, attempt, next_retry_time = rm._retry_batches[0]
        
        assert batch_data == batch
        assert attempt == 1
        # Should use Retry-After value (30 seconds)
        assert next_retry_time >= initial_time + 29.5  # Allow for small timing variations
        assert next_retry_time <= initial_time + 30.5
    
    def test_add_failed_batch_without_retry_after(self):
        """Test adding failed batch without Retry-After header."""
        rm = RetryManager(max_retries=3, initial_backoff_ms=1000, max_backoff_ms=10000, jitter_factor=0)
        
        batch = [{"message": "test"}]
        
        initial_time = time.time()
        rm.add_failed_batch(batch)
        
        # Should use initial backoff
        assert len(rm._retry_batches) == 1
        batch_data, attempt, next_retry_time = rm._retry_batches[0]
        
        assert next_retry_time >= initial_time + 0.9  # 1000ms with some tolerance
        assert next_retry_time <= initial_time + 1.1
    
    def test_exponential_backoff_progression(self):
        """Test exponential backoff progression."""
        rm = RetryManager(max_retries=5, initial_backoff_ms=100, max_backoff_ms=5000, jitter_factor=0)
        
        batch = [{"message": "test"}]
        rm.add_failed_batch(batch)
        
        # Make the first retry immediately ready
        rm._retry_batches[0] = (rm._retry_batches[0][0], rm._retry_batches[0][1], time.time() - 1)
        
        # Simulate multiple retry attempts
        for expected_attempt in range(1, 4):
            ready_batches = rm.get_ready_batches()
            assert len(ready_batches) == 1
            
            if expected_attempt < 3:
                # Should still have retries remaining
                assert len(rm._retry_batches) == 1
                _, attempt, _ = rm._retry_batches[0]
                assert attempt == expected_attempt + 1
                
                # Make next retry ready immediately
                if rm._retry_batches:
                    rm._retry_batches[0] = (rm._retry_batches[0][0], rm._retry_batches[0][1], time.time() - 1)
    
    def test_max_retries_exceeded(self):
        """Test batch is dropped after max retries."""
        rm = RetryManager(max_retries=2, initial_backoff_ms=100, max_backoff_ms=1000, jitter_factor=0)
        
        batch = [{"message": "test"}]
        rm.add_failed_batch(batch)
        
        # Exhaust all retries
        for _ in range(3):  # initial + 2 retries = 3 total
            rm._retry_batches[0] = (rm._retry_batches[0][0], rm._retry_batches[0][1], time.time() - 1)
            ready_batches = rm.get_ready_batches()
            
        # Should be no more retry batches
        assert len(rm._retry_batches) == 0


class TestEdgeNodeIdempotencyManager:
    """Test idempotency manager for edge node."""
    
    @pytest.mark.asyncio
    async def test_generate_batch_key(self):
        """Test batch key generation."""
        im = IdempotencyManager(3600)  # Use positional argument
        
        batch = [
            {"message": "test1", "timestamp": "2023-01-01T00:00:00Z"},
            {"message": "test2", "timestamp": "2023-01-01T00:00:01Z"}
        ]
        
        key = await im.generate_batch_key(batch)
        
        assert isinstance(key, str)
        assert len(key) == 32  # MD5 hex digest
        
        # Same batch should generate same key
        key2 = await im.generate_batch_key(batch)
        assert key == key2
    
    @pytest.mark.asyncio
    async def test_duplicate_detection(self):
        """Test duplicate batch detection."""
        im = IdempotencyManager(3600)  # Use positional argument
        
        key = "test_batch_key"
        
        # First time should not be duplicate
        is_dup1 = await im.is_duplicate(key)
        assert is_dup1 is False
        
        # Second time should be duplicate
        is_dup2 = await im.is_duplicate(key)
        assert is_dup2 is True
    
    @pytest.mark.asyncio
    async def test_key_expiration(self):
        """Test key expiration after window."""
        im = IdempotencyManager(1)  # 1 second window, use positional argument
        
        key = "test_key"
        
        # Add key
        await im.is_duplicate(key)
        
        # Wait for expiration
        await asyncio.sleep(1.2)
        
        # Should not be duplicate after expiration
        is_dup = await im.is_duplicate(key)
        assert is_dup is False


class TestBandwidthLimiter:
    """Test bandwidth limiter."""
    
    def test_bandwidth_limiter_initialization(self):
        """Test bandwidth limiter initialization."""
        bl = BandwidthLimiter(bytes_per_sec=1024, burst_bytes=2048)
        
        assert bl.bytes_per_sec == 1024
        assert bl.burst_bytes == 2048
        assert bl._tokens == 2048.0
    
    def test_can_send_within_burst(self):
        """Test sending within burst limit."""
        bl = BandwidthLimiter(bytes_per_sec=1000, burst_bytes=2000)
        
        # Should be able to send within burst
        assert bl.can_send(1500) is True
        assert bl._tokens == 500.0  # 2000 - 1500
    
    def test_can_send_exceeds_tokens(self):
        """Test sending when exceeding available tokens."""
        bl = BandwidthLimiter(bytes_per_sec=1000, burst_bytes=1000)
        
        # Use up all tokens
        assert bl.can_send(1000) is True
        
        # Should not be able to send more
        assert bl.can_send(100) is False
    
    def test_token_replenishment(self):
        """Test tokens are replenished over time."""
        bl = BandwidthLimiter(bytes_per_sec=1000, burst_bytes=1000)
        
        # Use up tokens
        bl.can_send(1000)
        assert bl._tokens == 0.0
        
        # Simulate time passing
        bl._last_update = time.time() - 1.0  # 1 second ago
        
        # Should replenish 1000 tokens
        bl._replenish_tokens()
        assert bl._tokens == 1000.0
    
    def test_get_wait_time(self):
        """Test wait time calculation."""
        bl = BandwidthLimiter(bytes_per_sec=1000, burst_bytes=1000)
        
        # Use up tokens
        bl.can_send(1000)
        
        # Should need to wait for more tokens
        wait_time = bl.get_wait_time(500)
        assert abs(wait_time - 0.5) < 0.01  # Allow for small floating point differences


class TestDLQManager:
    """Test Dead Letter Queue manager."""
    
    def test_dlq_manager_initialization(self):
        """Test DLQ manager creates directory."""
        with tempfile.TemporaryDirectory() as temp_dir:
            dlq_dir = os.path.join(temp_dir, "dlq")
            dlq = DLQManager(dlq_dir)
            
            assert os.path.exists(dlq_dir)
            assert dlq.dlq_dir == Path(dlq_dir)
    
    def test_send_to_dlq(self):
        """Test sending message to DLQ."""
        with tempfile.TemporaryDirectory() as temp_dir:
            dlq_dir = os.path.join(temp_dir, "dlq")
            dlq = DLQManager(dlq_dir)
            
            message = {"message": "test", "timestamp": "2023-01-01T00:00:00Z"}
            dlq.send_to_dlq(message, "test_failure", attempts=3)
            
            # Should create a DLQ file
            dlq_files = list(Path(dlq_dir).glob("dlq-*.json"))
            assert len(dlq_files) == 1
            
            # Check file content
            with open(dlq_files[0]) as f:
                dlq_entry = json.load(f)
            
            assert dlq_entry['original_message'] == message
            assert dlq_entry['reason'] == "test_failure"
            assert dlq_entry['attempts'] == 3
            assert 'dlq_timestamp' in dlq_entry
            assert 'message_hash' in dlq_entry
    
    def test_get_dlq_count(self):
        """Test DLQ count."""
        with tempfile.TemporaryDirectory() as temp_dir:
            dlq_dir = os.path.join(temp_dir, "dlq")
            dlq = DLQManager(dlq_dir)
            
            assert dlq.get_dlq_count() == 0
            
            # Add messages to DLQ
            dlq.send_to_dlq({"msg": "1"}, "test", 1)
            dlq.send_to_dlq({"msg": "2"}, "test", 1)
            
            # Small delay to ensure files are written
            time.sleep(0.01)
            
            assert dlq.get_dlq_count() == 2


class TestPersistentQueue:
    """Test persistent queue functionality."""
    
    def test_persistent_queue_disabled(self):
        """Test queue when disabled."""
        config = {'enabled': False}
        pq = PersistentQueue(config)
        
        assert pq.enabled is False
        assert pq.enqueue({"message": "test"}) is True  # Pass-through
    
    def test_persistent_queue_initialization(self):
        """Test queue initialization."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config = {
                'enabled': True,
                'dir': os.path.join(temp_dir, "queue"),
                'max_bytes': 1024 * 1024,
                'flush_interval_ms': 1000,
                'dlq_dir': os.path.join(temp_dir, "dlq"),
                'flush_bandwidth_bytes_per_sec': 512 * 1024
            }
            
            pq = PersistentQueue(config)
            
            assert pq.enabled is True
            assert pq.max_bytes == 1024 * 1024
            assert pq.flush_interval_ms == 1000
            assert os.path.exists(config['dir'])
            assert os.path.exists(config['dlq_dir'])
    
    def test_enqueue_message(self):
        """Test enqueuing messages."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config = {
                'enabled': True,
                'dir': os.path.join(temp_dir, "queue"),
                'max_bytes': 1024 * 1024
            }
            
            pq = PersistentQueue(config)
            
            message = {"message": "test", "timestamp": "2023-01-01T00:00:00Z"}
            result = pq.enqueue(message)
            
            assert result is True
            
            # Check that message was stored
            stats = pq.get_stats()
            assert stats['pending_messages'] == 1
    
    def test_queue_backpressure(self):
        """Test queue applies backpressure when full."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config = {
                'enabled': True,
                'dir': os.path.join(temp_dir, "queue"),
                'max_bytes': 100  # Very small limit for testing
            }
            
            pq = PersistentQueue(config)
            
            # Fill queue beyond capacity
            large_message = {"message": "x" * 200}  # Larger than max_bytes
            result = pq.enqueue(large_message)
            
            # Should reject due to backpressure
            assert result is False
    
    @pytest.mark.asyncio
    async def test_queue_start_stop(self):
        """Test queue start and stop."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config = {
                'enabled': True,
                'dir': os.path.join(temp_dir, "queue"),
                'flush_interval_ms': 100  # Fast flush for testing
            }
            
            pq = PersistentQueue(config)
            
            await pq.start()
            assert pq._running is True
            assert pq._flush_task is not None
            
            await pq.stop()
            assert pq._running is False
    
    def test_get_stats(self):
        """Test queue statistics."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config = {
                'enabled': True,
                'dir': os.path.join(temp_dir, "queue"),
                'max_bytes': 1024 * 1024,
                'flush_bandwidth_bytes_per_sec': 512 * 1024
            }
            
            pq = PersistentQueue(config)
            
            stats = pq.get_stats()
            
            assert stats['enabled'] is True
            assert stats['max_bytes'] == 1024 * 1024
            assert stats['bandwidth_limit_bps'] == 512 * 1024
            assert 'pending_messages' in stats
            assert 'queue_dir' in stats
    
    def test_is_healthy(self):
        """Test queue health check."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config = {
                'enabled': True,
                'dir': os.path.join(temp_dir, "queue"),
                'max_bytes': 1000
            }
            
            pq = PersistentQueue(config)
            
            # Empty queue should be healthy
            assert pq.is_healthy() is True
            
            # Mock queue being mostly full (over 80%)
            pq.get_current_size_bytes = lambda: 900  # 90% of 1000
            assert pq.is_healthy() is False


# Integration tests
class TestReliabilityIntegration:
    """Test integration of reliability components."""
    
    @pytest.mark.asyncio 
    async def test_full_reliability_stack(self):
        """Test complete reliability stack with mocked HTTP transport."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Mock HTTP client that fails then succeeds
            mock_response_fail = Mock()
            mock_response_fail.raise_for_status.side_effect = httpx.HTTPStatusError(
                "Server error", request=Mock(), response=Mock(status_code=500, headers={})
            )
            
            mock_response_success = Mock()
            mock_response_success.raise_for_status.return_value = None
            mock_response_success.status_code = 200
            mock_response_success.headers = {}
            
            with patch('httpx.AsyncClient') as mock_client_class:
                mock_client = mock_client_class.return_value
                mock_client.post = AsyncMock(side_effect=[mock_response_fail, mock_response_success])
                
                # Test configuration with all reliability features
                from app.output.shipper import DataShipper, MessageBuffer
                from app.config import get_config_manager
                
                config = {
                    'url': 'https://example.com/ingest',
                    'batch_size': 10,
                    'retry': {
                        'max_retries': 3,
                        'initial_backoff_ms': 10,  # Fast for testing
                        'max_backoff_ms': 100,
                        'jitter_factor': 0
                    },
                    'idempotency': {
                        'window_sec': 3600
                    },
                    'queue': {
                        'enabled': True,
                        'dir': os.path.join(temp_dir, 'queue'),
                        'flush_bandwidth_bytes_per_sec': 1024*1024
                    }
                }
                
                buffer = MessageBuffer(max_size=1000)
                shipper = DataShipper(config, buffer)
                
                # Add test message
                buffer.put({"message": "test message", "timestamp": "2023-01-01T00:00:00Z"})
                
                await shipper.start()
                
                # Let it process
                await asyncio.sleep(0.1)
                
                await shipper.stop()
                
                # Should have attempted request twice (fail then success)
                assert mock_client.post.call_count == 2
                
                # Check statistics
                stats = shipper.get_stats()
                assert stats['total_batches_sent'] == 1
                assert stats['total_retries'] >= 1