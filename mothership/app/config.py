"""Configuration management for Mothership with dual-sink support."""
import os
import signal
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List
import yaml
import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger()


class LokiConfig(BaseModel):
    """Loki sink configuration."""
    enabled: bool = Field(default=False)
    url: str = Field(default="http://localhost:3100")
    tenant_id: Optional[str] = Field(default=None)
    username: Optional[str] = Field(default=None)
    password: Optional[str] = Field(default=None)
    batch_size: int = Field(default=100)
    batch_timeout_seconds: float = Field(default=5.0)
    max_retries: int = Field(default=3)
    retry_backoff_seconds: float = Field(default=1.0)
    timeout_seconds: float = Field(default=30.0)
    
    def __init__(self, **data):
        """Initialize LokiConfig, reading from environment variables if not provided."""
        # Set defaults from environment variables if not explicitly provided
        if 'enabled' not in data:
            data['enabled'] = os.getenv('LOKI_ENABLED', 'false').lower() in ('true', '1', 'yes', 'on')
        if 'url' not in data:
            data['url'] = os.getenv('LOKI_URL', 'http://localhost:3100')
        if 'tenant_id' not in data:
            data['tenant_id'] = os.getenv('LOKI_TENANT_ID')
        if 'username' not in data:
            data['username'] = os.getenv('LOKI_USERNAME')
        if 'password' not in data:
            data['password'] = os.getenv('LOKI_PASSWORD')
        if 'batch_size' not in data:
            data['batch_size'] = int(os.getenv('LOKI_BATCH_SIZE', '100'))
        if 'batch_timeout_seconds' not in data:
            data['batch_timeout_seconds'] = float(os.getenv('LOKI_BATCH_TIMEOUT_SECONDS', '5.0'))
        if 'max_retries' not in data:
            data['max_retries'] = int(os.getenv('LOKI_MAX_RETRIES', '3'))
        if 'retry_backoff_seconds' not in data:
            data['retry_backoff_seconds'] = float(os.getenv('LOKI_RETRY_BACKOFF_SECONDS', '1.0'))
        if 'timeout_seconds' not in data:
            data['timeout_seconds'] = float(os.getenv('LOKI_TIMEOUT_SECONDS', '30.0'))
        super().__init__(**data)
    
    def get(self, key: str, default: Any = None) -> Any:
        """Dictionary-style get method for backward compatibility."""
        return getattr(self, key, default)
    
    def __getitem__(self, key: str) -> Any:
        """Dictionary-style access for backward compatibility."""
        return getattr(self, key)
        
    def __setitem__(self, key: str, value: Any) -> None:
        """Dictionary-style assignment for backward compatibility.""" 
        setattr(self, key, value)
        
    def keys(self):
        """Return the field names."""
        return self.model_fields.keys()
        
    def model_dump_dict(self) -> Dict[str, Any]:
        """Return as dictionary for compatibility."""
        return self.model_dump()
    
    @classmethod
    def from_env(cls) -> "LokiConfig":
        """Create LokiConfig from environment variables."""
        return cls()


class TSDBConfig(BaseModel):
    """TimescaleDB sink configuration.""" 
    enabled: bool = Field(default=True)
    host: str = Field(default="localhost")
    port: int = Field(default=5432)
    database: str = Field(default="edgebot")
    username: str = Field(default="edgebot")
    password: str = Field(default="edgebot")
    
    def __init__(self, **data):
        """Initialize TSDBConfig, reading from environment variables if not provided."""
        # Set defaults from environment variables if not explicitly provided
        if 'enabled' not in data:
            data['enabled'] = os.getenv('TSDB_ENABLED', 'true').lower() in ('true', '1', 'yes', 'on')
        if 'host' not in data:
            data['host'] = os.getenv('TSDB_HOST', 'localhost')
        if 'port' not in data:
            data['port'] = int(os.getenv('TSDB_PORT', '5432'))
        if 'database' not in data:
            data['database'] = os.getenv('TSDB_DATABASE', 'edgebot')
        if 'username' not in data:
            data['username'] = os.getenv('TSDB_USERNAME', 'edgebot')
        if 'password' not in data:
            data['password'] = os.getenv('TSDB_PASSWORD', 'edgebot')
        super().__init__(**data)
    
    @classmethod
    def from_env(cls) -> "TSDBConfig":
        """Create TSDBConfig from environment variables."""
        return cls()


class AppConfig(BaseModel):
    """Main application configuration."""
    loki: LokiConfig = Field(default_factory=LokiConfig)
    tsdb: TSDBConfig = Field(default_factory=TSDBConfig)
    
    @classmethod
    def from_env(cls) -> "AppConfig":
        """Create AppConfig from environment variables."""
        return cls(
            loki=LokiConfig(),
            tsdb=TSDBConfig()
        )
    
    def get_enabled_sinks(self) -> List[str]:
        """Get list of enabled sink names."""
        enabled = []
        if self.tsdb.enabled:
            enabled.append('tsdb')
        if self.loki.enabled:
            enabled.append('loki')
        return enabled


def get_config() -> AppConfig:
    """Get application configuration from environment."""
    return AppConfig.from_env()

class ConfigManager:
    """Manages configuration loading and hot-reloading with dual-sink support."""
    
    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = Path(config_path)
        self._config = {}
        self._callbacks = []
        
        # Set up signal handler for hot reload
        signal.signal(signal.SIGHUP, self._handle_sighup)
        
        # Load config on initialization
        self.load_config()
        
    def _handle_sighup(self, signum, frame):
        """Handle SIGHUP for configuration hot-reload."""
        logger.info("Received SIGHUP, reloading configuration")
        try:
            self.load_config()
            # Notify callbacks of config change
            for callback in self._callbacks:
                callback(self._config)
        except Exception as e:
            logger.error("Failed to reload configuration", error=str(e))
    
    def register_reload_callback(self, callback):
        """Register a callback to be called when config is reloaded."""
        self._callbacks.append(callback)
    
    def load_config(self) -> Dict[str, Any]:
        """Load configuration from YAML file with environment overrides."""
        try:
            # Load YAML configuration
            if self.config_path.exists():
                with open(self.config_path, 'r') as f:
                    self._config = yaml.safe_load(f)
            else:
                logger.warning(f"Config file {self.config_path} not found, using defaults")
                self._config = self._get_default_config()
            
            # Apply environment variable overrides
            self._apply_env_overrides()
            
            # Validate configuration
            self._validate_config()
            
            logger.info("Configuration loaded successfully", 
                       config_file=str(self.config_path),
                       enabled_sinks=self.get_enabled_sinks())
            return self._config
            
        except Exception as e:
            logger.error("Failed to load configuration", error=str(e))
            raise
    
    def _apply_env_overrides(self):
        """Apply environment variable overrides to configuration."""
        # Server configuration
        if os.getenv('MOTHERSHIP_HOST'):
            self._config.setdefault('server', {})['host'] = os.getenv('MOTHERSHIP_HOST')
        if os.getenv('MOTHERSHIP_PORT'):
            self._config.setdefault('server', {})['port'] = int(os.getenv('MOTHERSHIP_PORT'))
        
        # Database configuration
        if os.getenv('MOTHERSHIP_DB_DSN'):
            self._config.setdefault('database', {})['dsn'] = os.getenv('MOTHERSHIP_DB_DSN')
        if os.getenv('MOTHERSHIP_DB_HOST'):
            self._config.setdefault('database', {})['host'] = os.getenv('MOTHERSHIP_DB_HOST')
        if os.getenv('MOTHERSHIP_DB_PORT'):
            self._config.setdefault('database', {})['port'] = int(os.getenv('MOTHERSHIP_DB_PORT'))
        if os.getenv('MOTHERSHIP_DB_NAME'):
            self._config.setdefault('database', {})['database'] = os.getenv('MOTHERSHIP_DB_NAME')
        if os.getenv('MOTHERSHIP_DB_USER'):
            self._config.setdefault('database', {})['user'] = os.getenv('MOTHERSHIP_DB_USER')
        if os.getenv('MOTHERSHIP_DB_PASS'):
            self._config.setdefault('database', {})['password'] = os.getenv('MOTHERSHIP_DB_PASS')
        
        # LLM configuration
        if os.getenv('MOTHERSHIP_LLM_ENABLED'):
            self._config.setdefault('llm', {})['enabled'] = os.getenv('MOTHERSHIP_LLM_ENABLED').lower() in ('true', '1', 'yes', 'on')
        if os.getenv('MOTHERSHIP_LLM_ENDPOINT'):
            self._config.setdefault('llm', {})['endpoint'] = os.getenv('MOTHERSHIP_LLM_ENDPOINT')
        if os.getenv('MOTHERSHIP_LLM_API_KEY'):
            self._config.setdefault('llm', {})['api_key'] = os.getenv('MOTHERSHIP_LLM_API_KEY')
        if os.getenv('MOTHERSHIP_LLM_MODEL'):
            self._config.setdefault('llm', {})['model'] = os.getenv('MOTHERSHIP_LLM_MODEL')
        if os.getenv('MOTHERSHIP_LLM_CONFIDENCE_THRESHOLD'):
            self._config.setdefault('llm', {})['confidence_threshold'] = float(os.getenv('MOTHERSHIP_LLM_CONFIDENCE_THRESHOLD'))
        
        # LLM Backend configuration
        if os.getenv('LLM_BACKEND'):
            self._config.setdefault('llm', {})['backend'] = os.getenv('LLM_BACKEND')
        
        # Ollama-specific configuration
        if os.getenv('OLLAMA_BASE_URL'):
            self._config.setdefault('llm', {})['ollama_base_url'] = os.getenv('OLLAMA_BASE_URL')
        if os.getenv('OLLAMA_MODEL'):
            self._config.setdefault('llm', {})['ollama_model'] = os.getenv('OLLAMA_MODEL')
        if os.getenv('OLLAMA_TIMEOUT_MS'):
            self._config.setdefault('llm', {})['ollama_timeout_ms'] = int(os.getenv('OLLAMA_TIMEOUT_MS'))
        if os.getenv('OLLAMA_MAX_TOKENS'):
            self._config.setdefault('llm', {})['ollama_max_tokens'] = int(os.getenv('OLLAMA_MAX_TOKENS'))
        
        # Loki sink configuration - NEW
        if os.getenv('LOKI_ENABLED'):
            self._config.setdefault('sinks', {}).setdefault('loki', {})['enabled'] = os.getenv('LOKI_ENABLED').lower() in ('true', '1', 'yes', 'on')
        if os.getenv('LOKI_URL'):
            self._config.setdefault('sinks', {}).setdefault('loki', {})['url'] = os.getenv('LOKI_URL')
        if os.getenv('LOKI_TENANT_ID'):
            self._config.setdefault('sinks', {}).setdefault('loki', {})['tenant_id'] = os.getenv('LOKI_TENANT_ID')
        if os.getenv('LOKI_USERNAME'):
            self._config.setdefault('sinks', {}).setdefault('loki', {})['username'] = os.getenv('LOKI_USERNAME')
        if os.getenv('LOKI_PASSWORD'):
            self._config.setdefault('sinks', {}).setdefault('loki', {})['password'] = os.getenv('LOKI_PASSWORD')
        if os.getenv('LOKI_BATCH_SIZE'):
            self._config.setdefault('sinks', {}).setdefault('loki', {})['batch_size'] = int(os.getenv('LOKI_BATCH_SIZE'))
        if os.getenv('LOKI_BATCH_TIMEOUT_SECONDS'):
            self._config.setdefault('sinks', {}).setdefault('loki', {})['batch_timeout_seconds'] = float(os.getenv('LOKI_BATCH_TIMEOUT_SECONDS'))

        # Loki reliability configuration
        if os.getenv('LOKI_MAX_RETRIES'):
            self._config.setdefault('sinks', {}).setdefault('loki', {}).setdefault('retry', {})['max_retries'] = int(os.getenv('LOKI_MAX_RETRIES'))
        if os.getenv('LOKI_INITIAL_BACKOFF_MS'):
            self._config.setdefault('sinks', {}).setdefault('loki', {}).setdefault('retry', {})['initial_backoff_ms'] = int(os.getenv('LOKI_INITIAL_BACKOFF_MS'))
        if os.getenv('LOKI_MAX_BACKOFF_MS'):
            self._config.setdefault('sinks', {}).setdefault('loki', {}).setdefault('retry', {})['max_backoff_ms'] = int(os.getenv('LOKI_MAX_BACKOFF_MS'))
        if os.getenv('LOKI_JITTER_FACTOR'):
            self._config.setdefault('sinks', {}).setdefault('loki', {}).setdefault('retry', {})['jitter_factor'] = float(os.getenv('LOKI_JITTER_FACTOR'))
        if os.getenv('LOKI_TIMEOUT_MS'):
            self._config.setdefault('sinks', {}).setdefault('loki', {}).setdefault('retry', {})['timeout_ms'] = int(os.getenv('LOKI_TIMEOUT_MS'))
        if os.getenv('LOKI_FAILURE_THRESHOLD'):
            self._config.setdefault('sinks', {}).setdefault('loki', {}).setdefault('circuit_breaker', {})['failure_threshold'] = int(os.getenv('LOKI_FAILURE_THRESHOLD'))
        if os.getenv('LOKI_OPEN_DURATION_SEC'):
            self._config.setdefault('sinks', {}).setdefault('loki', {}).setdefault('circuit_breaker', {})['open_duration_sec'] = int(os.getenv('LOKI_OPEN_DURATION_SEC'))
        if os.getenv('LOKI_HALF_OPEN_MAX_INFLIGHT'):
            self._config.setdefault('sinks', {}).setdefault('loki', {}).setdefault('circuit_breaker', {})['half_open_max_inflight'] = int(os.getenv('LOKI_HALF_OPEN_MAX_INFLIGHT'))
        if os.getenv('LOKI_QUEUE_ENABLED'):
            self._config.setdefault('sinks', {}).setdefault('loki', {}).setdefault('queue', {})['enabled'] = os.getenv('LOKI_QUEUE_ENABLED').lower() in ('true', '1', 'yes', 'on')
        if os.getenv('LOKI_QUEUE_DIR'):
            self._config.setdefault('sinks', {}).setdefault('loki', {}).setdefault('queue', {})['queue_dir'] = os.getenv('LOKI_QUEUE_DIR')
        if os.getenv('LOKI_QUEUE_MAX_BYTES'):
            self._config.setdefault('sinks', {}).setdefault('loki', {}).setdefault('queue', {})['queue_max_bytes'] = int(os.getenv('LOKI_QUEUE_MAX_BYTES'))
        if os.getenv('LOKI_QUEUE_FLUSH_INTERVAL_MS'):
            self._config.setdefault('sinks', {}).setdefault('loki', {}).setdefault('queue', {})['queue_flush_interval_ms'] = int(os.getenv('LOKI_QUEUE_FLUSH_INTERVAL_MS'))
        if os.getenv('LOKI_DLQ_DIR'):
            self._config.setdefault('sinks', {}).setdefault('loki', {}).setdefault('queue', {})['dlq_dir'] = os.getenv('LOKI_DLQ_DIR')
        
        # TimescaleDB sink configuration - NEW
        if os.getenv('TSDB_ENABLED'):
            self._config.setdefault('sinks', {}).setdefault('timescaledb', {})['enabled'] = os.getenv('TSDB_ENABLED').lower() in ('true', '1', 'yes', 'on')

        # TSDB reliability configuration
        if os.getenv('TSDB_MAX_RETRIES'):
            self._config.setdefault('sinks', {}).setdefault('timescaledb', {}).setdefault('retry', {})['max_retries'] = int(os.getenv('TSDB_MAX_RETRIES'))
        if os.getenv('TSDB_INITIAL_BACKOFF_MS'):
            self._config.setdefault('sinks', {}).setdefault('timescaledb', {}).setdefault('retry', {})['initial_backoff_ms'] = int(os.getenv('TSDB_INITIAL_BACKOFF_MS'))
        if os.getenv('TSDB_MAX_BACKOFF_MS'):
            self._config.setdefault('sinks', {}).setdefault('timescaledb', {}).setdefault('retry', {})['max_backoff_ms'] = int(os.getenv('TSDB_MAX_BACKOFF_MS'))
        if os.getenv('TSDB_JITTER_FACTOR'):
            self._config.setdefault('sinks', {}).setdefault('timescaledb', {}).setdefault('retry', {})['jitter_factor'] = float(os.getenv('TSDB_JITTER_FACTOR'))
        if os.getenv('TSDB_TIMEOUT_MS'):
            self._config.setdefault('sinks', {}).setdefault('timescaledb', {}).setdefault('retry', {})['timeout_ms'] = int(os.getenv('TSDB_TIMEOUT_MS'))
        if os.getenv('TSDB_FAILURE_THRESHOLD'):
            self._config.setdefault('sinks', {}).setdefault('timescaledb', {}).setdefault('circuit_breaker', {})['failure_threshold'] = int(os.getenv('TSDB_FAILURE_THRESHOLD'))
        if os.getenv('TSDB_OPEN_DURATION_SEC'):
            self._config.setdefault('sinks', {}).setdefault('timescaledb', {}).setdefault('circuit_breaker', {})['open_duration_sec'] = int(os.getenv('TSDB_OPEN_DURATION_SEC'))
        if os.getenv('TSDB_HALF_OPEN_MAX_INFLIGHT'):
            self._config.setdefault('sinks', {}).setdefault('timescaledb', {}).setdefault('circuit_breaker', {})['half_open_max_inflight'] = int(os.getenv('TSDB_HALF_OPEN_MAX_INFLIGHT'))
        if os.getenv('TSDB_QUEUE_ENABLED'):
            self._config.setdefault('sinks', {}).setdefault('timescaledb', {}).setdefault('queue', {})['enabled'] = os.getenv('TSDB_QUEUE_ENABLED').lower() in ('true', '1', 'yes', 'on')
        if os.getenv('TSDB_QUEUE_DIR'):
            self._config.setdefault('sinks', {}).setdefault('timescaledb', {}).setdefault('queue', {})['queue_dir'] = os.getenv('TSDB_QUEUE_DIR')
        if os.getenv('TSDB_QUEUE_MAX_BYTES'):
            self._config.setdefault('sinks', {}).setdefault('timescaledb', {}).setdefault('queue', {})['queue_max_bytes'] = int(os.getenv('TSDB_QUEUE_MAX_BYTES'))
        if os.getenv('TSDB_QUEUE_FLUSH_INTERVAL_MS'):
            self._config.setdefault('sinks', {}).setdefault('timescaledb', {}).setdefault('queue', {})['queue_flush_interval_ms'] = int(os.getenv('TSDB_QUEUE_FLUSH_INTERVAL_MS'))
        if os.getenv('TSDB_DLQ_DIR'):
            self._config.setdefault('sinks', {}).setdefault('timescaledb', {}).setdefault('queue', {})['dlq_dir'] = os.getenv('TSDB_DLQ_DIR')
        
        # Sink reliability configuration (new SATCOM-friendly defaults)
        if os.getenv('SINK_DEFAULT_MAX_RETRIES'):
            self._config.setdefault('sink_defaults', {})['max_retries'] = int(os.getenv('SINK_DEFAULT_MAX_RETRIES'))
        if os.getenv('SINK_DEFAULT_INITIAL_BACKOFF_MS'):
            self._config.setdefault('sink_defaults', {})['initial_backoff_ms'] = int(os.getenv('SINK_DEFAULT_INITIAL_BACKOFF_MS'))
        if os.getenv('SINK_DEFAULT_MAX_BACKOFF_MS'):
            self._config.setdefault('sink_defaults', {})['max_backoff_ms'] = int(os.getenv('SINK_DEFAULT_MAX_BACKOFF_MS'))
        if os.getenv('SINK_DEFAULT_JITTER_FACTOR'):
            self._config.setdefault('sink_defaults', {})['jitter_factor'] = float(os.getenv('SINK_DEFAULT_JITTER_FACTOR'))
        if os.getenv('SINK_DEFAULT_TIMEOUT_MS'):
            self._config.setdefault('sink_defaults', {})['timeout_ms'] = int(os.getenv('SINK_DEFAULT_TIMEOUT_MS'))
        if os.getenv('SINK_DEFAULT_FAILURE_THRESHOLD'):
            self._config.setdefault('sink_defaults', {})['failure_threshold'] = int(os.getenv('SINK_DEFAULT_FAILURE_THRESHOLD'))
        if os.getenv('SINK_DEFAULT_OPEN_DURATION_SEC'):
            self._config.setdefault('sink_defaults', {})['open_duration_sec'] = int(os.getenv('SINK_DEFAULT_OPEN_DURATION_SEC'))
        if os.getenv('SINK_DEFAULT_HALF_OPEN_MAX_INFLIGHT'):
            self._config.setdefault('sink_defaults', {})['half_open_max_inflight'] = int(os.getenv('SINK_DEFAULT_HALF_OPEN_MAX_INFLIGHT'))
        
        # Idempotency configuration
        if os.getenv('IDEMPOTENCY_WINDOW_SEC'):
            self._config.setdefault('idempotency', {})['window_sec'] = int(os.getenv('IDEMPOTENCY_WINDOW_SEC'))
        
        # Reliability configuration - NEW
        reliability_config = self._config.setdefault('reliability', {})
        
        # Retry configuration
        if os.getenv('SINK_DEFAULT_MAX_RETRIES'):
            reliability_config['max_retries'] = int(os.getenv('SINK_DEFAULT_MAX_RETRIES'))
        if os.getenv('SINK_DEFAULT_INITIAL_BACKOFF_MS'):
            reliability_config['initial_backoff_ms'] = int(os.getenv('SINK_DEFAULT_INITIAL_BACKOFF_MS'))
        if os.getenv('SINK_DEFAULT_MAX_BACKOFF_MS'):
            reliability_config['max_backoff_ms'] = int(os.getenv('SINK_DEFAULT_MAX_BACKOFF_MS'))
        if os.getenv('SINK_DEFAULT_JITTER_FACTOR'):
            reliability_config['jitter_factor'] = float(os.getenv('SINK_DEFAULT_JITTER_FACTOR'))
        if os.getenv('SINK_DEFAULT_TIMEOUT_MS'):
            reliability_config['timeout_ms'] = int(os.getenv('SINK_DEFAULT_TIMEOUT_MS'))
            
        # Circuit breaker configuration
        if os.getenv('SINK_DEFAULT_FAILURE_THRESHOLD'):
            reliability_config['failure_threshold'] = int(os.getenv('SINK_DEFAULT_FAILURE_THRESHOLD'))
        if os.getenv('SINK_DEFAULT_OPEN_DURATION_SEC'):
            reliability_config['open_duration_sec'] = int(os.getenv('SINK_DEFAULT_OPEN_DURATION_SEC'))
        if os.getenv('SINK_DEFAULT_HALF_OPEN_MAX_INFLIGHT'):
            reliability_config['half_open_max_inflight'] = int(os.getenv('SINK_DEFAULT_HALF_OPEN_MAX_INFLIGHT'))
            
        # Persistent queue configuration
        if os.getenv('QUEUE_ENABLED'):
            reliability_config['queue_enabled'] = os.getenv('QUEUE_ENABLED').lower() in ('true', '1', 'yes', 'on')
        if os.getenv('QUEUE_DIR'):
            reliability_config['queue_dir'] = os.getenv('QUEUE_DIR')
        if os.getenv('QUEUE_MAX_BYTES'):
            reliability_config['queue_max_bytes'] = int(os.getenv('QUEUE_MAX_BYTES'))
        if os.getenv('QUEUE_FLUSH_INTERVAL_MS'):
            reliability_config['queue_flush_interval_ms'] = int(os.getenv('QUEUE_FLUSH_INTERVAL_MS'))
        if os.getenv('DLQ_DIR'):
            reliability_config['dlq_dir'] = os.getenv('DLQ_DIR')
        if os.getenv('FLUSH_BANDWIDTH_BYTES_PER_SEC'):
            reliability_config['flush_bandwidth_bytes_per_sec'] = int(os.getenv('FLUSH_BANDWIDTH_BYTES_PER_SEC'))
        if os.getenv('IDEMPOTENCY_WINDOW_SEC'):
            reliability_config['idempotency_window_sec'] = int(os.getenv('IDEMPOTENCY_WINDOW_SEC'))
        
        # Logging
        if os.getenv('MOTHERSHIP_LOG_LEVEL'):
            self._config.setdefault('logging', {})['level'] = os.getenv('MOTHERSHIP_LOG_LEVEL')
    
    def _validate_config(self):
        """Validate configuration values."""
        # Validate required sections
        required_sections = ['server', 'database', 'pipeline']
        for section in required_sections:
            if section not in self._config:
                raise ValueError(f"Missing required configuration section: {section}")
        
        # Validate server configuration
        server = self._config['server']
        if 'host' not in server or 'port' not in server:
            raise ValueError("Server section must contain 'host' and 'port'")
        
        # Validate database configuration
        database = self._config['database']
        if 'dsn' not in database and not all(key in database for key in ['host', 'port', 'database', 'user']):
            raise ValueError("Database section must contain 'dsn' or connection parameters (host, port, database, user)")
        
        # Validate sinks configuration
        sinks = self._config.get('sinks', {})
        if sinks.get('loki', {}).get('enabled', False):
            loki_config = sinks['loki']
            if 'url' not in loki_config:
                raise ValueError("Loki sink is enabled but 'url' is not configured")
    
    def _get_default_config(self) -> Dict[str, Any]:
        """Get default configuration with dual-sink support."""
        return {
            'server': {
                'host': '0.0.0.0',
                'port': 8443
            },
            'database': {
                'host': 'localhost',
                'port': 5432,
                'database': 'mothership',
                'user': 'mothership',
                'password': 'mothership'
            },
            'pipeline': {
                'processors': {
                    'redaction': {
                        'enabled': True,
                        'drop_fields': ['password', 'secret', 'token', 'key', 'credential'],
                        'mask_patterns': [
                            r'password=\S+',
                            r'token=\S+',
                            r'key=\S+',
                            r'\b\d{3}-\d{2}-\d{4}\b'  # SSN pattern
                        ],
                        'hash_fields': ['user', 'username', 'email']
                    },
                    'enrichment': {
                        'enabled': True,
                        'add_tags': {
                            'processed_by': 'mothership',
                            'version': '1.5'
                        },
                        'severity_mapping': {
                            'emergency': 0, 'alert': 1, 'critical': 2, 'error': 3,
                            'warning': 4, 'notice': 5, 'informational': 6, 'debug': 7
                        }
                    }
                }
            },
            'llm': {
                'enabled': False,
                'backend': 'openai',  # 'openai' or 'ollama'
                'endpoint': 'https://api.openai.com/v1',
                'model': 'gpt-3.5-turbo',
                'confidence_threshold': 0.8,
                'max_tokens': 150,
                'temperature': 0.0,
                # Ollama-specific settings
                'ollama_base_url': 'http://localhost:11434',
                'ollama_model': 'llama3.1:8b-instruct-q4_0',
                'ollama_timeout_ms': 30000,
                'ollama_max_tokens': 150
            },
            'sinks': {
                'timescaledb': {
                    'enabled': True  # Default enabled
                },
                'loki': {
                    'enabled': False,  # Default disabled
                    'url': 'http://localhost:3100',
                    'tenant_id': None,
                    'username': None,
                    'password': None,
                    'batch_size': 100,
                    'batch_timeout_seconds': 5.0,
                    'max_retries': 3,
                    'retry_backoff_seconds': 1.0,
                    'timeout_seconds': 30.0
                }
            },
            'sink_defaults': {
                # SATCOM-friendly defaults (safe for satellite/at-sea networks)
                'max_retries': 5,
                'initial_backoff_ms': 500,
                'max_backoff_ms': 30000,
                'jitter_factor': 0.2,
                'timeout_ms': 5000,
                'failure_threshold': 5,
                'open_duration_sec': 60,
                'half_open_max_inflight': 1
            },
            'idempotency': {
                'window_sec': 3600  # 1 hour deduplication window
            },
            'logging': {
                'level': 'INFO',
                'structured': True
            }
        }
    
    def get_config(self) -> Dict[str, Any]:
        """Get current configuration."""
        return self._config.copy()
    
    def get_enabled_sinks(self) -> list:
        """Get list of enabled sink names."""
        enabled = []
        sinks = self._config.get('sinks', {})
        
        if sinks.get('timescaledb', {}).get('enabled', True):
            enabled.append('timescaledb')
        if sinks.get('loki', {}).get('enabled', False):
            enabled.append('loki')
            
        return enabled
