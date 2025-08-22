"""Configuration management for Mothership."""
import os
import signal
import logging
from pathlib import Path
from typing import Dict, Any, Optional
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
    
    def _get_default_config(self) -> Dict[str, Any]:
        """Get default configuration."""
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
                'endpoint': 'https://api.openai.com/v1',
                'model': 'gpt-3.5-turbo',
                'confidence_threshold': 0.8,
                'max_tokens': 150,
                'temperature': 0.0
            },
            'logging': {
                'level': 'INFO',
                'structured': True
            }
        }
    
    def get_config(self) -> Dict[str, Any]:
        """Get current configuration."""
        return self._config.copy()