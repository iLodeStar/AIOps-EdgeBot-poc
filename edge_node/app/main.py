"""Main entry point for EdgeBot."""
import asyncio
import signal
import sys
import os
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
import structlog
import click
import uvloop

# Version information
__version__ = "1.0.0"

# Add the app directory to the path so we can import our modules
sys.path.insert(0, str(Path(__file__).parent))

from config import get_config_manager, get_config
from inputs.syslog_server import create_syslog_server
from inputs.snmp_poll import create_snmp_poller
from inputs.weather import create_weather_poller
from output.shipper import create_output_shipper

# Configure structured logging
def configure_logging(config: Dict[str, Any]):
    """Configure structured logging."""
    log_config = config.get('logging', {})
    level = log_config.get('level', 'INFO')
    format_type = log_config.get('format', 'json')
    log_file = log_config.get('file')
    
    # Configure basic logging
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format='%(message)s',
        stream=sys.stdout if log_file is None else open(log_file, 'a')
    )
    
    # Configure structlog
    processors = [
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="ISO"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    
    if format_type == 'json':
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())
    
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


class HealthServer:
    """Simple health check server."""
    
    def __init__(self, config: Dict[str, Any], services: Dict[str, Any]):
        self.config = config
        self.services = services
        self.app = None
        self.server = None
    
    async def health_check(self, request):
        """Health check endpoint."""
        from aiohttp import web
        
        health_status = {
            'status': 'healthy',
            'timestamp': structlog.processors.TimeStamper()._stamper(),
            'services': {},
            'version': '1.0.0'
        }
        
        overall_healthy = True
        
        # Check each service
        for name, service in self.services.items():
            try:
                if hasattr(service, 'is_running') and hasattr(service, 'get_status'):
                    status = service.get_status() if hasattr(service, 'get_status') else {}
                    is_healthy = service.is_running() if hasattr(service, 'is_running') else True
                elif hasattr(service, 'is_healthy'):
                    is_healthy = service.is_healthy()
                    status = service.get_stats() if hasattr(service, 'get_stats') else {}
                else:
                    is_healthy = True
                    status = {}
                
                health_status['services'][name] = {
                    'healthy': is_healthy,
                    'status': status
                }
                
                if not is_healthy:
                    overall_healthy = False
                    
            except Exception as e:
                health_status['services'][name] = {
                    'healthy': False,
                    'error': str(e)
                }
                overall_healthy = False
        
        if not overall_healthy:
            health_status['status'] = 'unhealthy'
            return web.json_response(health_status, status=503)
        
        return web.json_response(health_status)
    
    async def metrics(self, request):
        """Prometheus metrics endpoint."""
        from aiohttp import web
        
        metrics = []
        
        # Service status metrics
        for name, service in self.services.items():
            try:
                if hasattr(service, 'get_stats'):
                    stats = service.get_stats()
                    
                    # Convert stats to Prometheus format
                    for metric_name, value in stats.items():
                        if isinstance(value, (int, float)):
                            prom_name = f"edgebot_{name}_{metric_name}".replace('-', '_')
                            metrics.append(f"{prom_name} {value}")
                        elif isinstance(value, dict):
                            for sub_name, sub_value in value.items():
                                if isinstance(sub_value, (int, float)):
                                    prom_name = f"edgebot_{name}_{metric_name}_{sub_name}".replace('-', '_')
                                    metrics.append(f"{prom_name} {sub_value}")
                
                if hasattr(service, 'is_running'):
                    running = 1 if service.is_running() else 0
                    metrics.append(f"edgebot_{name}_running {running}")
                
            except Exception as e:
                structlog.get_logger().warning(f"Error collecting metrics for {name}", error=str(e))
        
        metrics_text = '\n'.join(metrics) + '\n'
        return web.Response(text=metrics_text, content_type='text/plain')
    
    async def start(self):
        """Start the health server."""
        try:
            from aiohttp import web
            
            self.app = web.Application()
            self.app.router.add_get(
                self.config.get('observability', {}).get('health_path', '/healthz'),
                self.health_check
            )
            self.app.router.add_get(
                self.config.get('observability', {}).get('metrics_path', '/metrics'),
                self.metrics
            )
            
            port = self.config.get('observability', {}).get('health_port', 8081)
            runner = web.AppRunner(self.app)
            await runner.setup()
            
            site = web.TCPSite(
                runner, 
                self.config.get('server', {}).get('host', '0.0.0.0'),
                port
            )
            await site.start()
            
            structlog.get_logger().info("Health server started", port=port)
            
        except ImportError:
            structlog.get_logger().warning("aiohttp not available, health server disabled")
    
    async def stop(self):
        """Stop the health server."""
        if self.app:
            await self.app.cleanup()


class EdgeBotSupervisor:
    """Main supervisor for EdgeBot services with self-healing capabilities."""
    
    def __init__(self, config_path: str):
        self.config_path = config_path
        self.config_manager = get_config_manager(config_path)
        self.config = self.config_manager.config
        
        # Services
        self.services = {}
        self.tasks = {}
        self.running = False
        self.shutdown_event = asyncio.Event()
        
        # Health server
        self.health_server = None
        
        # Message callback for input services
        self.output_shipper = None
        
        # Configure logging
        configure_logging(self.config)
        self.logger = structlog.get_logger(__name__)
        
        # Register config reload callback
        self.config_manager.register_reload_callback(self._on_config_reload)
    
    async def _on_config_reload(self, new_config: Dict[str, Any]):
        """Handle configuration reload."""
        self.logger.info("Configuration reloaded, restarting services")
        self.config = new_config
        
        # Restart services with new configuration
        await self._restart_services()
    
    async def _message_callback(self, message: Dict[str, Any]):
        """Callback for input services to send messages."""
        if self.output_shipper:
            try:
                await self.output_shipper.send_message(message)
            except Exception as e:
                self.logger.error("Error sending message to output shipper", 
                                error=str(e), message_type=message.get('type'))
    
    async def _create_services(self):
        """Create all services based on configuration."""
        try:
            # Create output shipper first
            output_config = self.config.get('output', {})
            self.output_shipper = create_output_shipper(output_config)
            self.services['output_shipper'] = self.output_shipper
            
            # Create input services
            inputs_config = self.config.get('inputs', {})
            
            # Syslog server
            if inputs_config.get('syslog', {}).get('enabled', False):
                syslog_server = create_syslog_server(
                    inputs_config['syslog'], 
                    self._message_callback
                )
                self.services['syslog_server'] = syslog_server
            
            # SNMP poller
            if inputs_config.get('snmp', {}).get('enabled', False):
                snmp_poller = create_snmp_poller(
                    inputs_config['snmp'],
                    self._message_callback
                )
                self.services['snmp_poller'] = snmp_poller
            
            # Weather poller
            if inputs_config.get('weather', {}).get('enabled', False):
                weather_poller = create_weather_poller(
                    inputs_config['weather'],
                    self._message_callback
                )
                self.services['weather_poller'] = weather_poller
            
            # Health server
            self.health_server = HealthServer(self.config, self.services)
            
            self.logger.info("Services created", count=len(self.services))
            
        except Exception as e:
            self.logger.error("Error creating services", error=str(e))
            raise
    
    async def _start_services(self):
        """Start all services."""
        for name, service in self.services.items():
            try:
                await service.start()
                self.logger.info("Service started", service=name)
            except Exception as e:
                self.logger.error("Error starting service", service=name, error=str(e))
                raise
        
        # Start health server
        if self.health_server:
            await self.health_server.start()
    
    async def _stop_services(self):
        """Stop all services."""
        # Stop health server first
        if self.health_server:
            await self.health_server.stop()
        
        # Stop services in reverse order
        for name, service in reversed(list(self.services.items())):
            try:
                await service.stop()
                self.logger.info("Service stopped", service=name)
            except Exception as e:
                self.logger.error("Error stopping service", service=name, error=str(e))
    
    async def _restart_services(self):
        """Restart all services with new configuration."""
        # Stop existing services
        await self._stop_services()
        
        # Clear services
        self.services.clear()
        
        # Recreate and restart
        await self._create_services()
        await self._start_services()
    
    async def _monitor_services(self):
        """Monitor services and restart failed ones (self-healing)."""
        while self.running:
            try:
                for name, service in list(self.services.items()):
                    # Check service health
                    is_healthy = True
                    
                    if hasattr(service, 'is_running'):
                        is_healthy = service.is_running()
                    elif hasattr(service, 'is_healthy'):
                        is_healthy = service.is_healthy()
                    
                    if not is_healthy:
                        self.logger.warning("Service unhealthy, restarting", service=name)
                        try:
                            await service.stop()
                            await service.start()
                            self.logger.info("Service restarted", service=name)
                        except Exception as e:
                            self.logger.error("Failed to restart service", 
                                            service=name, error=str(e))
                
                # Wait before next check
                await asyncio.sleep(30)  # Check every 30 seconds
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Error in service monitoring", error=str(e))
                await asyncio.sleep(60)  # Back off on error
    
    def _setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown."""
        def signal_handler(signum, frame):
            self.logger.info("Received shutdown signal", signal=signum)
            self.shutdown_event.set()
        
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)
    
    async def start(self):
        """Start EdgeBot."""
        try:
            self.logger.info("Starting EdgeBot", config=self.config_path)
            
            # Setup signal handlers
            self._setup_signal_handlers()
            
            # Create and start services
            await self._create_services()
            await self._start_services()
            
            self.running = True
            
            # Start service monitoring
            monitor_task = asyncio.create_task(self._monitor_services())
            
            self.logger.info("EdgeBot started successfully")
            
            # Wait for shutdown signal
            await self.shutdown_event.wait()
            
            self.logger.info("Shutting down EdgeBot...")
            
            # Stop monitoring
            self.running = False
            monitor_task.cancel()
            try:
                await monitor_task
            except asyncio.CancelledError:
                pass
            
            # Stop services
            await self._stop_services()
            
            self.logger.info("EdgeBot shutdown complete")
            
        except Exception as e:
            self.logger.error("Error running EdgeBot", error=str(e))
            raise


@click.command()
@click.option('--config', '-c', default='config.yaml', help='Configuration file path')
@click.option('--log-level', '-l', default=None, help='Override log level')
@click.option('--dry-run', is_flag=True, help='Validate configuration and exit')
@click.option('--version', is_flag=True, help='Show version and exit')
def main(config: str, log_level: Optional[str], dry_run: bool, version: bool):
    """EdgeBot - Lightweight edge node data collector and shipper."""
    
    # Handle version flag
    if version:
        print(f"EdgeBot v{__version__}")
        sys.exit(0)
    
    # Log version information
    print(f"EdgeBot v{__version__} starting...")
    
    # Check if config file exists
    config_path = Path(config)
    if not config_path.exists() and config == 'config.yaml':
        # Try to find config in the same directory as the script
        script_dir = Path(__file__).parent.parent
        alt_config_path = script_dir / 'config.yaml'
        if alt_config_path.exists():
            config_path = alt_config_path
        else:
            print(f"Configuration file not found: {config}")
            sys.exit(1)
    
    try:
        # Load configuration for validation
        config_manager = get_config_manager(str(config_path))
        
        # Override log level if specified
        if log_level:
            config_manager.config.setdefault('logging', {})['level'] = log_level.upper()
        
        if dry_run:
            print("Configuration validation successful")
            print(f"Loaded configuration from: {config_path}")
            print(f"Services enabled:")
            
            inputs = config_manager.config.get('inputs', {})
            for service, service_config in inputs.items():
                enabled = service_config.get('enabled', False)
                print(f"  - {service}: {'enabled' if enabled else 'disabled'}")
            
            sys.exit(0)
        
        # Use uvloop for better performance on Unix
        if sys.platform != 'win32':
            try:
                uvloop.install()
            except ImportError:
                pass  # uvloop not available, continue with default event loop
        
        # Create and run EdgeBot
        supervisor = EdgeBotSupervisor(str(config_path))
        asyncio.run(supervisor.start())
        
    except KeyboardInterrupt:
        print("\nShutdown requested by user")
        sys.exit(0)
    except Exception as e:
        print(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()