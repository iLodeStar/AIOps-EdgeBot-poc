"""Integration tests for the SinksManager with reliability features."""

import tempfile
from pathlib import Path
import pytest
from unittest.mock import Mock, AsyncMock, patch

from mothership.app.storage.sinks import SinksManager
from mothership.app.config import ConfigManager


class TestSinksManagerIntegration:
    """Test SinksManager integration with reliability features."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        
        # Create a minimal config with reliability features enabled
        self.config = {
            'sinks': {
                'timescaledb': {'enabled': True},
                'loki': {'enabled': False}
            },
            'reliability': {
                'max_retries': 2,
                'initial_backoff_ms': 10,
                'max_backoff_ms': 100,
                'jitter_factor': 0.0,
                'timeout_ms': 1000,
                'failure_threshold': 2,
                'open_duration_sec': 1,
                'half_open_max_inflight': 1,
                'queue_enabled': True,
                'queue_dir': f'{self.temp_dir}/queue',
                'queue_max_bytes': 1024 * 1024,
                'queue_flush_interval_ms': 1000,
                'dlq_dir': f'{self.temp_dir}/dlq',
                'flush_bandwidth_bytes_per_sec': 1024,
                'idempotency_window_sec': 10
            }
        }
    
    def test_sinks_manager_initialization(self):
        """Test that SinksManager initializes correctly with reliability features."""
        manager = SinksManager(self.config)
        
        # Should have one sink (tsdb)
        assert len(manager.sinks) == 1
        assert 'tsdb' in manager.sinks
        
        # Should have reliability components
        assert manager.persistent_queue is not None
        assert manager.idempotency_manager is not None
        
        # Check queue directories were created
        queue_dir = Path(self.config['reliability']['queue_dir'])
        dlq_dir = Path(self.config['reliability']['dlq_dir'])
        assert queue_dir.exists()
        assert dlq_dir.exists()
    
    def test_sinks_manager_stats(self):
        """Test that stats include reliability information."""
        manager = SinksManager(self.config)
        stats = manager.get_stats()
        
        assert stats['enabled_sinks'] == ['tsdb']
        assert stats['sink_count'] == 1
        assert stats['persistent_queue_enabled'] is True
        assert stats['idempotency_enabled'] is True
        assert 'queue_stats' in stats
    
    @pytest.mark.asyncio
    async def test_write_events_basic(self):
        """Test basic write events functionality."""
        manager = SinksManager(self.config)
        
        # Mock the underlying sink
        mock_sink = Mock()
        mock_sink.write_events = AsyncMock(return_value={"written": 2, "errors": 0})
        manager.sinks['tsdb'].sink = mock_sink
        
        events = [
            {"message": "Event 1", "timestamp": "2023-01-01T00:00:00Z"},
            {"message": "Event 2", "timestamp": "2023-01-01T00:01:00Z"}
        ]
        
        result = await manager.write_events(events)
        
        assert 'tsdb' in result
        assert result['tsdb']['written'] == 2
        assert result['tsdb']['errors'] == 0
        
        # Verify sink was called
        mock_sink.write_events.assert_called_once_with(events)
    
    @pytest.mark.asyncio
    async def test_idempotency_check(self):
        """Test that duplicate events are detected."""
        manager = SinksManager(self.config)
        
        # Mock the underlying sink
        mock_sink = Mock()
        mock_sink.write_events = AsyncMock(return_value={"written": 1, "errors": 0})
        manager.sinks['tsdb'].sink = mock_sink
        
        events = [{"message": "Same event", "id": "unique-123"}]
        
        # First write should proceed
        result1 = await manager.write_events(events)
        assert 'tsdb' in result1
        assert result1['tsdb']['written'] == 1
        
        # Second write should be detected as duplicate
        result2 = await manager.write_events(events)
        assert 'duplicate' in result2
        assert result2['duplicate']['skipped'] == 1
        
        # Sink should only be called once
        mock_sink.write_events.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_queue_on_failure(self):
        """Test that failed events are queued."""
        manager = SinksManager(self.config)
        
        # Mock the underlying sink to fail
        mock_sink = Mock()
        mock_sink.write_events = AsyncMock(return_value={"written": 0, "errors": 2})
        manager.sinks['tsdb'].sink = mock_sink
        
        events = [
            {"message": "Event 1"},
            {"message": "Event 2"}
        ]
        
        result = await manager.write_events(events)
        
        assert 'tsdb' in result
        assert result['tsdb']['errors'] == 2
        assert result['tsdb'].get('queued', 0) == 2
        
        # Check queue stats
        stats = manager.get_stats()
        queue_stats = stats['queue_stats']
        assert queue_stats['file_count'] == 1  # One file queued
        assert queue_stats['current_bytes'] > 0
    
    def test_config_defaults(self):
        """Test that config defaults are applied correctly."""
        # Use ConfigManager to get defaults
        config_manager = ConfigManager()
        config = config_manager.get_config()
        
        # Check reliability defaults
        reliability = config['reliability']
        assert reliability['max_retries'] == 5
        assert reliability['initial_backoff_ms'] == 500
        assert reliability['max_backoff_ms'] == 30000
        assert reliability['jitter_factor'] == 0.2
        assert reliability['timeout_ms'] == 5000
        assert reliability['failure_threshold'] == 5
        assert reliability['open_duration_sec'] == 60
        assert reliability['half_open_max_inflight'] == 3
        assert reliability['queue_enabled'] is True
        assert reliability['queue_dir'] == './data/queue'
        assert reliability['queue_max_bytes'] == 1073741824  # 1 GiB
        assert reliability['flush_bandwidth_bytes_per_sec'] == 1048576  # 1 MiB/s
        assert reliability['idempotency_window_sec'] == 86400  # 24 hours
    
    def test_env_var_overrides(self):
        """Test that environment variables override config."""
        import os
        
        # Set environment variables
        env_vars = {
            'SINK_DEFAULT_MAX_RETRIES': '7',
            'SINK_DEFAULT_INITIAL_BACKOFF_MS': '1000',
            'SINK_DEFAULT_JITTER_FACTOR': '0.3',
            'QUEUE_ENABLED': 'false',
            'QUEUE_MAX_BYTES': '5368709120',  # 5 GiB
            'FLUSH_BANDWIDTH_BYTES_PER_SEC': '524288'  # 0.5 MiB/s
        }
        
        for key, value in env_vars.items():
            os.environ[key] = value
        
        try:
            config_manager = ConfigManager()
            config = config_manager.get_config()
            
            reliability = config['reliability']
            assert reliability['max_retries'] == 7
            assert reliability['initial_backoff_ms'] == 1000
            assert reliability['jitter_factor'] == 0.3
            assert reliability['queue_enabled'] is False
            assert reliability['queue_max_bytes'] == 5368709120
            assert reliability['flush_bandwidth_bytes_per_sec'] == 524288
            
        finally:
            # Clean up environment variables
            for key in env_vars:
                os.environ.pop(key, None)


@pytest.fixture
def mock_loki_config():
    """Mock Loki configuration for testing."""
    return {
        'enabled': True,
        'url': 'http://localhost:3100',
        'batch_size': 10,
        'batch_timeout_seconds': 1.0
    }


class TestLokiIntegration:
    """Test Loki integration with reliability features."""
    
    @pytest.mark.asyncio
    async def test_loki_sink_with_retries(self, mock_loki_config):
        """Test that Loki sink works with retry wrapper."""
        config = {
            'sinks': {
                'timescaledb': {'enabled': False},
                'loki': mock_loki_config
            },
            'reliability': {
                'max_retries': 2,
                'initial_backoff_ms': 10,
                'failure_threshold': 3
            }
        }
        
        manager = SinksManager(config)
        
        assert 'loki' in manager.sinks
        assert len(manager.sinks) == 1
        
        # Test that the sink is wrapped with reliability features
        loki_wrapper = manager.sinks['loki']
        assert hasattr(loki_wrapper, 'retry_manager')
        assert hasattr(loki_wrapper, 'circuit_breaker')
        
        # Check retry config
        assert loki_wrapper.retry_manager.config.max_retries == 2
        assert loki_wrapper.retry_manager.config.initial_backoff_ms == 10
        
        # Check circuit breaker config
        assert loki_wrapper.circuit_breaker.config.failure_threshold == 3