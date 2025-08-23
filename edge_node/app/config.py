"""Configuration management for EdgeBot."""
import os
import signal
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List
import yaml
import structlog

logger = structlog.get_logger()

class ConfigManager:
    """Manages configuration loading and hot-reloading."""
    
    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = Path(config_path)
        self._config = {}
        self._callbacks = []
        
        # Set up signal handler for hot reload
        signal.signal(signal.SIGHUP, self._handle_sighup)
        
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
            
            logger.info("Configuration loaded successfully", config_file=str(self.config_path))
            return self._config
            
        except Exception as e:
            logger.error("Failed to load configuration", error=str(e))
            raise
    
    def _apply_env_overrides(self):
        """Apply environment variable overrides to configuration."""
        # Server configuration
        if os.getenv('EDGEBOT_HOST'):
            self._config.setdefault('server', {})['host'] = os.getenv('EDGEBOT_HOST')
        if os.getenv('EDGEBOT_PORT'):
            self._config.setdefault('server', {})['port'] = int(os.getenv('EDGEBOT_PORT'))
        
        # Logging
        if os.getenv('EDGEBOT_LOG_LEVEL'):
            self._config.setdefault('logging', {})['level'] = os.getenv('EDGEBOT_LOG_LEVEL')
        
        # Output configuration
        if os.getenv('EDGEBOT_MOTHERSHIP_URL'):
            self._config.setdefault('output', {}).setdefault('mothership', {})['url'] = os.getenv('EDGEBOT_MOTHERSHIP_URL')
        if os.getenv('EDGEBOT_AUTH_TOKEN'):
            self._config.setdefault('output', {}).setdefault('mothership', {})['auth_token'] = os.getenv('EDGEBOT_AUTH_TOKEN')
        
        # Input configuration
        if os.getenv('EDGEBOT_SYSLOG_UDP_PORT'):
            self._config.setdefault('inputs', {}).setdefault('syslog', {})['udp_port'] = int(os.getenv('EDGEBOT_SYSLOG_UDP_PORT'))
        if os.getenv('EDGEBOT_SYSLOG_TCP_PORT'):
            self._config.setdefault('inputs', {}).setdefault('syslog', {})['tcp_port'] = int(os.getenv('EDGEBOT_SYSLOG_TCP_PORT'))
        
        # Weather configuration
        if os.getenv('EDGEBOT_WEATHER_LAT'):
            self._config.setdefault('inputs', {}).setdefault('weather', {})['latitude'] = float(os.getenv('EDGEBOT_WEATHER_LAT'))
        if os.getenv('EDGEBOT_WEATHER_LON'):
            self._config.setdefault('inputs', {}).setdefault('weather', {})['longitude'] = float(os.getenv('EDGEBOT_WEATHER_LON'))
        if os.getenv('EDGEBOT_WEATHER_CITY'):
            self._config.setdefault('inputs', {}).setdefault('weather', {})['city'] = os.getenv('EDGEBOT_WEATHER_CITY')
        
        # NMEA input configuration  
        if os.getenv('EDGEBOT_NMEA_ENABLED'):
            self._config.setdefault('inputs', {}).setdefault('nmea', {})['enabled'] = os.getenv('EDGEBOT_NMEA_ENABLED').lower() in ('true', '1', 'yes', 'on')
        if os.getenv('EDGEBOT_NMEA_UDP_PORT'):
            self._config.setdefault('inputs', {}).setdefault('nmea', {})['udp_port'] = int(os.getenv('EDGEBOT_NMEA_UDP_PORT'))
        
        # Persistent queue configuration (new)
        if os.getenv('QUEUE_ENABLED'):
            self._config.setdefault('queue', {})['enabled'] = os.getenv('QUEUE_ENABLED').lower() in ('true', '1', 'yes', 'on')
        if os.getenv('QUEUE_DIR'):
            self._config.setdefault('queue', {})['dir'] = os.getenv('QUEUE_DIR')
        if os.getenv('QUEUE_MAX_BYTES'):
            self._config.setdefault('queue', {})['max_bytes'] = int(os.getenv('QUEUE_MAX_BYTES'))
        if os.getenv('QUEUE_FLUSH_INTERVAL_MS'):
            self._config.setdefault('queue', {})['flush_interval_ms'] = int(os.getenv('QUEUE_FLUSH_INTERVAL_MS'))
        if os.getenv('DLQ_DIR'):
            self._config.setdefault('queue', {})['dlq_dir'] = os.getenv('DLQ_DIR')
        if os.getenv('FLUSH_BANDWIDTH_BYTES_PER_SEC'):
            self._config.setdefault('queue', {})['flush_bandwidth_bytes_per_sec'] = int(os.getenv('FLUSH_BANDWIDTH_BYTES_PER_SEC'))
        
        # Idempotency configuration  
        if os.getenv('IDEMPOTENCY_WINDOW_SEC'):
            self._config.setdefault('idempotency', {})['window_sec'] = int(os.getenv('IDEMPOTENCY_WINDOW_SEC'))
    
    def _validate_config(self):
        """Validate configuration values."""
        # Validate required sections
        required_sections = ['server', 'inputs', 'output', 'observability']
        for section in required_sections:
            if section not in self._config:
                raise ValueError(f"Missing required configuration section: {section}")
        
        # Validate server configuration
        server = self._config['server']
        if 'host' not in server or 'port' not in server:
            raise ValueError("Server section must contain 'host' and 'port'")
        
        # Validate output configuration
        output = self._config['output']
        if 'mothership' not in output:
            raise ValueError("Output section must contain 'mothership' configuration")
        
        mothership = output['mothership']
        if 'url' not in mothership:
            raise ValueError("Mothership configuration must contain 'url'")
        
        # Validate weather configuration if enabled
        weather = self._config.get('inputs', {}).get('weather', {})
        if weather.get('enabled', False):
            has_coords = weather.get('latitude') is not None and weather.get('longitude') is not None
            has_city = weather.get('city') is not None
            if not (has_coords or has_city):
                raise ValueError("Weather input requires either latitude/longitude or city")
    
    def _get_default_config(self) -> Dict[str, Any]:
        """Return default configuration."""
        return {
            'server': {
                'host': '0.0.0.0',
                'port': 8080,
                'workers': 1
            },
            'logging': {
                'level': 'INFO',
                'format': 'json',
                'file': None
            },
            'inputs': {
                'syslog': {
                    'enabled': True,
                    'udp_port': 5514,
                    'tcp_port': 5515,
                    'bind_address': '0.0.0.0',
                    'max_message_size': 8192
                },
                'snmp': {
                    'enabled': False,
                    'targets': []
                },
                'weather': {
                    'enabled': False,
                    'latitude': 28.6139,
                    'longitude': 77.2090,
                    'city': None,
                    'interval': 3600,
                    'api_timeout': 30
                },
                'logs': {
                    'enabled': False,
                    'paths': [],
                    'globs': [],
                    'from_beginning': False,
                    'scan_interval': 2,
                    'read_chunk': 8192
                },
                'flows': {
                    'enabled': False,
                    'netflow_ports': [2055],
                    'ipfix_ports': [4739],
                    'sflow_ports': [6343]
                },
                'nmea': {
                    'enabled': False,
                    'mode': 'udp',
                    'bind_address': '0.0.0.0',
                    'udp_port': 10110,
                    'tcp_port': 10110
                },
                'discovery': {
                    'enabled': False,
                    'interval': 300,
                    'auto_tail_logs': True,
                    'extra_logs': []
                }
            },
            'output': {
                'mothership': {
                    'url': 'https://localhost:8443/ingest',
                    'auth_token': None,
                    'batch_size': 100,
                    'batch_timeout': 5.0,
                    'max_retries': 3,
                    'retry_backoff': 1.0,
                    'compression': True,
                    'tls_verify': True,
                    'tls_client_cert': None,
                    'tls_client_key': None
                }
            },
            'observability': {
                'health_port': 8081,
                'metrics_port': 8082,
                'metrics_path': '/metrics',
                'health_path': '/healthz'
            },
            'buffer': {
                'max_size': 10000,
                'disk_buffer': False,
                'disk_buffer_path': '/tmp/edgebot_buffer.db',
                'disk_buffer_max_size': '100MB'
            },
            'queue': {
                'enabled': False,  # Optional persistent queue
                'dir': '/var/lib/edgebot/queue',
                'max_bytes': 100*1024*1024,  # 100MB
                'flush_interval_ms': 5000,   # 5 seconds
                'dlq_dir': '/var/lib/edgebot/dlq',
                'flush_bandwidth_bytes_per_sec': 1024*1024  # 1MB/s default limit
            },
            'idempotency': {
                'window_sec': 3600  # 1 hour deduplication window
            }
        }
    
    @property
    def config(self) -> Dict[str, Any]:
        """Get the current configuration."""
        return self._config
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value using dot notation."""
        keys = key.split('.')
        value = self._config
        
        try:
            for k in keys:
                value = value[k]
            return value
        except (KeyError, TypeError):
            return default


# Global configuration instance
_config_manager: Optional[ConfigManager] = None

def get_config_manager(config_path: str = "config.yaml") -> ConfigManager:
    """Get the global configuration manager instance."""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager(config_path)
        _config_manager.load_config()
    return _config_manager

def get_config() -> Dict[str, Any]:
    """Get the current configuration."""
    return get_config_manager().config