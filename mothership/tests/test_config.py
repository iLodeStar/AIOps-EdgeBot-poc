"""Tests for configuration management."""

import os
import pytest
from unittest.mock import patch

from mothership.app.config import LokiConfig, TSDBConfig, AppConfig, get_config


class TestLokiConfig:
    """Test Loki configuration."""
    
    def test_default_config(self):
        """Test default Loki configuration values."""
        config = LokiConfig()
        
        assert config.enabled is False
        assert config.url == "http://localhost:3100"
        assert config.tenant_id is None
        assert config.username is None
        assert config.password is None
        assert config.batch_size == 100
        assert config.batch_timeout_seconds == 5.0
        assert config.max_retries == 3
        assert config.retry_backoff_seconds == 1.0
        assert config.timeout_seconds == 30.0
    
    @patch.dict(os.environ, {
        'LOKI_ENABLED': 'true',
        'LOKI_URL': 'http://loki.example.com:3100',
        'LOKI_TENANT_ID': 'tenant1',
        'LOKI_USERNAME': 'user',
        'LOKI_PASSWORD': 'pass',
        'LOKI_BATCH_SIZE': '50'
    })
    def test_env_config(self):
        """Test Loki configuration from environment variables."""
        config = LokiConfig()
        
        assert config.enabled is True
        assert config.url == "http://loki.example.com:3100"
        assert config.tenant_id == "tenant1"
        assert config.username == "user"
        assert config.password == "pass"
        assert config.batch_size == 50


class TestTSDBConfig:
    """Test TimescaleDB configuration."""
    
    def test_default_config(self):
        """Test default TSDB configuration values."""
        config = TSDBConfig()
        
        assert config.enabled is True
        assert config.host == "localhost"
        assert config.port == 5432
        assert config.database == "edgebot"
        assert config.username == "edgebot"
        assert config.password == "edgebot"
    
    @patch.dict(os.environ, {
        'TSDB_ENABLED': 'false',
        'TSDB_HOST': 'db.example.com',
        'TSDB_PORT': '5433',
        'TSDB_DATABASE': 'mydb',
        'TSDB_USERNAME': 'myuser',
        'TSDB_PASSWORD': 'mypass'
    })
    def test_env_config(self):
        """Test TSDB configuration from environment variables."""
        config = TSDBConfig()
        
        assert config.enabled is False
        assert config.host == "db.example.com"
        assert config.port == 5433
        assert config.database == "mydb"
        assert config.username == "myuser"
        assert config.password == "mypass"


class TestAppConfig:
    """Test main application configuration."""
    
    def test_default_enabled_sinks(self):
        """Test default enabled sinks (TSDB only)."""
        config = AppConfig.from_env()
        
        enabled_sinks = config.get_enabled_sinks()
        assert "tsdb" in enabled_sinks
        assert "loki" not in enabled_sinks
    
    @patch.dict(os.environ, {
        'LOKI_ENABLED': 'true',
        'TSDB_ENABLED': 'true'
    })
    def test_dual_sinks_enabled(self):
        """Test when both sinks are enabled."""
        config = AppConfig.from_env()
        
        enabled_sinks = config.get_enabled_sinks()
        assert "tsdb" in enabled_sinks
        assert "loki" in enabled_sinks
        assert len(enabled_sinks) == 2
    
    @patch.dict(os.environ, {
        'LOKI_ENABLED': 'true',
        'TSDB_ENABLED': 'false'
    })
    def test_loki_only_enabled(self):
        """Test when only Loki is enabled."""
        config = AppConfig.from_env()
        
        enabled_sinks = config.get_enabled_sinks()
        assert "tsdb" not in enabled_sinks
        assert "loki" in enabled_sinks
        assert len(enabled_sinks) == 1
    
    @patch.dict(os.environ, {
        'LOKI_ENABLED': 'false',
        'TSDB_ENABLED': 'false'
    })
    def test_no_sinks_enabled(self):
        """Test when no sinks are enabled."""
        config = AppConfig.from_env()
        
        enabled_sinks = config.get_enabled_sinks()
        assert len(enabled_sinks) == 0


class TestGetConfig:
    """Test the get_config function."""
    
    def test_get_config_default(self):
        """Test getting default configuration."""
        config = get_config()
        
        assert isinstance(config, AppConfig)
        assert isinstance(config.loki, LokiConfig)
        assert isinstance(config.tsdb, TSDBConfig)
        
        # Should have TSDB enabled by default
        assert config.tsdb.enabled is True
        assert config.loki.enabled is False