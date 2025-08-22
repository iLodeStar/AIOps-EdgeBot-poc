"""Configuration management for the mothership."""

import os
from typing import Dict, Any, Optional, List
from pydantic import Field
from pydantic_settings import BaseSettings
import structlog

logger = structlog.get_logger(__name__)


class LokiConfig(BaseSettings):
    """Loki configuration settings."""
    
    enabled: bool = Field(default=False, description="Enable Loki sink")
    url: str = Field(default="http://localhost:3100", description="Loki API URL")
    tenant_id: Optional[str] = Field(default=None, description="Loki tenant ID for multi-tenancy")
    username: Optional[str] = Field(default=None, description="Basic auth username")
    password: Optional[str] = Field(default=None, description="Basic auth password")
    
    # Batching and performance
    batch_size: int = Field(default=100, description="Max events per batch")
    batch_timeout_seconds: float = Field(default=5.0, description="Max time to wait before sending partial batch")
    max_retries: int = Field(default=3, description="Max retries for failed requests")
    retry_backoff_seconds: float = Field(default=1.0, description="Base backoff time for retries")
    
    # HTTP client settings
    timeout_seconds: float = Field(default=30.0, description="HTTP request timeout")
    
    model_config = {"env_prefix": "LOKI_"}


class TSDBConfig(BaseSettings):
    """TimescaleDB configuration settings."""
    
    enabled: bool = Field(default=True, description="Enable TimescaleDB sink")
    host: str = Field(default="localhost", description="Database host")
    port: int = Field(default=5432, description="Database port")
    database: str = Field(default="edgebot", description="Database name")
    username: str = Field(default="edgebot", description="Database user")
    password: str = Field(default="edgebot", description="Database password")
    
    # Connection pool
    pool_size: int = Field(default=10, description="Connection pool size")
    max_overflow: int = Field(default=20, description="Max connections beyond pool size")
    
    model_config = {"env_prefix": "TSDB_"}


class ServerConfig(BaseSettings):
    """Server configuration settings."""
    
    host: str = Field(default="0.0.0.0", description="Server bind host")
    port: int = Field(default=8080, description="Server port")
    
    model_config = {"env_prefix": "SERVER_"}


class AppConfig(BaseSettings):
    """Main application configuration."""
    
    # Sub-configurations
    loki: LokiConfig = Field(default_factory=LokiConfig)
    tsdb: TSDBConfig = Field(default_factory=TSDBConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    
    # General settings
    log_level: str = Field(default="INFO", description="Logging level")
    
    @classmethod
    def from_env(cls) -> 'AppConfig':
        """Create configuration from environment variables."""
        return cls(
            loki=LokiConfig(),
            tsdb=TSDBConfig(),
            server=ServerConfig()
        )
    
    def get_enabled_sinks(self) -> List[str]:
        """Get list of enabled sink names."""
        enabled = []
        if self.tsdb.enabled:
            enabled.append("tsdb")
        if self.loki.enabled:
            enabled.append("loki")
        return enabled


def get_config() -> AppConfig:
    """Get application configuration from environment."""
    config = AppConfig.from_env()
    logger.info("Configuration loaded", 
                enabled_sinks=config.get_enabled_sinks(),
                loki_enabled=config.loki.enabled,
                tsdb_enabled=config.tsdb.enabled)
    return config