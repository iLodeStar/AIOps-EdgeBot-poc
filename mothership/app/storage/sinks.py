"""Storage sinks manager for dual writes to TimescaleDB and Loki."""

import asyncio
from typing import Dict, Any, List, Optional, Protocol
from abc import ABC, abstractmethod
import structlog

from .loki import LokiClient
from ..metrics import mship_sink_write_seconds
from ..reliability import CircuitBreaker, RetryManager, IdempotencyManager

logger = structlog.get_logger(__name__)


class StorageSink(Protocol):
    """Protocol for storage sinks."""
    
    async def start(self) -> None:
        """Start the sink."""
        ...
    
    async def stop(self) -> None:
        """Stop the sink."""
        ...
    
    async def write_events(self, events: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Write events and return stats."""
        ...
    
    def is_healthy(self) -> bool:
        """Check if sink is healthy."""
        ...


class TSDBSink:
    """TimescaleDB sink wrapper (placeholder implementation)."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self._healthy = False
        
    async def start(self):
        """Start the TSDB sink."""
        if not self.config.get('enabled', True):
            logger.debug("TSDB sink disabled, not starting")
            return
            
        # TODO: Implement actual TimescaleDB connection
        # For now, simulate successful start
        self._healthy = True
        logger.info("TSDB sink started (placeholder)",
                   enabled=self.config.get('enabled', True))
    
    async def stop(self):
        """Stop the TSDB sink."""
        # TODO: Close database connections
        self._healthy = False
        logger.info("TSDB sink stopped")
    
    async def write_events(self, events: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Write events to TimescaleDB."""
        if not self.config.get('enabled', True) or not events:
            return {"written": 0, "errors": 0}
            
        # TODO: Implement actual database writes
        # For now, simulate successful writes
        logger.debug("TSDB write (placeholder)", events=len(events))
        return {"written": len(events), "errors": 0}
    
    async def health_check(self) -> bool:
        """Check if TSDB sink is healthy."""
        return self._healthy and self.config.get('enabled', True)
    
    def is_enabled(self) -> bool:
        """Check if sink is enabled."""
        return self.config.get('enabled', True)
    
    def is_healthy(self) -> bool:
        """Check if TSDB sink is healthy."""
        return self._healthy and self.config.get('enabled', True)


class LokiSink:
    """Loki sink wrapper."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.client = LokiClient(config)
    
    async def start(self):
        """Start the Loki sink."""
        await self.client.start()
    
    async def stop(self):
        """Stop the Loki sink."""
        await self.client.stop()
    
    async def write_events(self, events: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Write events to Loki."""
        return await self.client.write_events(events)
    
    async def health_check(self) -> bool:
        """Check if Loki sink is healthy."""
        # For now, just check if it's enabled
        # TODO: Add actual health check (ping Loki /ready endpoint)
        return self.config.get('enabled', False)
    
    def is_enabled(self) -> bool:
        """Check if sink is enabled."""
        return self.config.get('enabled', False)
    
    def is_healthy(self) -> bool:
        """Check if Loki sink is healthy."""
        # For now, just check if it's enabled
        # TODO: Add actual health check (ping Loki /ready endpoint)
        return self.config.get('enabled', False)


class SinksManager:
    """Manages writes to multiple storage sinks."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.sinks: Dict[str, StorageSink] = {}
        
        # Get sink defaults and idempotency config
        self.sink_defaults = config.get('sink_defaults', {})
        idempotency_config = config.get('idempotency', {})
        
        # Initialize reliability components
        self.circuit_breakers: Dict[str, CircuitBreaker] = {}
        self.retry_managers: Dict[str, RetryManager] = {}
        self.idempotency_manager = IdempotencyManager(idempotency_config)
        
        # Initialize sinks based on configuration
        sinks_config = config.get('sinks', {})
        
        if sinks_config.get('timescaledb', {}).get('enabled', True):
            sink_name = "tsdb"
            self.sinks[sink_name] = TSDBSink(sinks_config.get('timescaledb', {}))
            self.circuit_breakers[sink_name] = CircuitBreaker(sink_name, self.sink_defaults)
            self.retry_managers[sink_name] = RetryManager(sink_name, self.sink_defaults)
            
        if sinks_config.get('loki', {}).get('enabled', False):
            sink_name = "loki"
            self.sinks[sink_name] = LokiSink(sinks_config.get('loki', {}))
            self.circuit_breakers[sink_name] = CircuitBreaker(sink_name, self.sink_defaults)
            self.retry_managers[sink_name] = RetryManager(sink_name, self.sink_defaults)
    
    async def start(self):
        """Start all enabled sinks."""
        start_tasks = []
        for name, sink in self.sinks.items():
            logger.info("Starting sink", sink=name)
            start_tasks.append(sink.start())
        
        if start_tasks:
            await asyncio.gather(*start_tasks, return_exceptions=True)
        
        logger.info("SinksManager started", 
                   enabled_sinks=list(self.sinks.keys()))
    
    async def stop(self):
        """Stop all sinks."""
        stop_tasks = []
        for name, sink in self.sinks.items():
            logger.info("Stopping sink", sink=name)
            stop_tasks.append(sink.stop())
        
        if stop_tasks:
            await asyncio.gather(*stop_tasks, return_exceptions=True)
        
        logger.info("SinksManager stopped")
    
    async def write_events(self, events: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """Write events to all enabled sinks and return per-sink stats."""
        if not events:
            return {}
        
        # Check for duplicate batch using idempotency
        batch_key = self.idempotency_manager.generate_batch_key(events)
        if self.idempotency_manager.is_duplicate(batch_key):
            logger.info("Skipping duplicate batch", 
                       events=len(events), 
                       batch_key=batch_key[:8])
            # Return successful results for all sinks to avoid retries
            return {name: {"written": len(events), "errors": 0} for name in self.sinks.keys()}
        
        # Fan out writes to all sinks concurrently (with circuit breaker protection)
        write_tasks = {}
        for name, sink in self.sinks.items():
            circuit_breaker = self.circuit_breakers[name]
            if circuit_breaker.can_execute():
                write_tasks[name] = asyncio.create_task(
                    self._reliable_write(name, sink, events)
                )
            else:
                logger.warning("Skipping sink due to open circuit breaker", sink=name)
                # Return error result for circuit-broken sinks
                write_tasks[name] = asyncio.create_task(
                    asyncio.coroutine(lambda: {"written": 0, "errors": len(events)})()
                )
        
        # Wait for all writes to complete
        results = {}
        for name, task in write_tasks.items():
            try:
                results[name] = await task
            except Exception as e:
                logger.error("Sink write failed", sink=name, error=str(e))
                results[name] = {"written": 0, "errors": len(events)}
        
        # Log summary
        total_written = sum(result.get("written", 0) for result in results.values())
        total_errors = sum(result.get("errors", 0) for result in results.values())
        
        logger.info("Multi-sink write completed",
                   events=len(events),
                   total_written=total_written,
                   total_errors=total_errors,
                   sink_results=results,
                   batch_key=batch_key[:8])
        
        return results
    
    async def _reliable_write(self, name: str, sink: StorageSink, events: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Write to a sink with circuit breaker and retry logic."""
        circuit_breaker = self.circuit_breakers[name]
        retry_manager = self.retry_managers[name]
        
        async def write_operation():
            try:
                # Observe per-sink write latency
                with mship_sink_write_seconds.labels(sink=name).time():
                    result = await sink.write_events(events)
                
                # Record success in circuit breaker
                circuit_breaker.record_success()
                return result
                
            except asyncio.TimeoutError:
                # Record timeout in circuit breaker
                circuit_breaker.record_timeout()
                raise
            except Exception as e:
                # Record failure in circuit breaker
                circuit_breaker.record_failure()
                raise
        
        try:
            # Execute with retry logic
            return await retry_manager.execute_with_retry(write_operation)
            
        except Exception as e:
            logger.error("Sink write failed after retries", sink=name, error=str(e))
            return {"written": 0, "errors": len(events)}
    
    async def _safe_write(self, name: str, sink: StorageSink, events: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Legacy safe write method - kept for compatibility."""
        try:
            # Observe per-sink write latency as required
            with mship_sink_write_seconds.labels(sink=name).time():
                return await sink.write_events(events)
        except Exception as e:
            logger.error("Sink write exception", sink=name, error=str(e))
            return {"written": 0, "errors": len(events)}
    
    def get_health_status(self) -> Dict[str, Any]:
        """Get health status of all sinks including circuit breaker states."""
        sink_health = {}
        overall_healthy = True
        
        for name, sink in self.sinks.items():
            is_healthy = sink.is_healthy()
            circuit_breaker = self.circuit_breakers[name]
            circuit_info = circuit_breaker.get_state_info()
            
            sink_health[name] = {
                "healthy": is_healthy,
                "enabled": True,
                "circuit_breaker": circuit_info
            }
            
            # Consider sink unhealthy if circuit is open
            if not is_healthy or circuit_info['state'] == 'OPEN':
                overall_healthy = False
        
        return {
            "healthy": overall_healthy,
            "sinks": sink_health,
            "enabled_sinks": list(self.sinks.keys()),
            "idempotency": self.idempotency_manager.get_stats()
        }
    
    def get_stats(self) -> Dict[str, Any]:
        """Get statistics from all sinks."""
        return {
            "enabled_sinks": list(self.sinks.keys()),
            "sink_count": len(self.sinks)
        }
    
    def get_sink_names(self) -> List[str]:
        """Get names of all configured sinks."""
        return list(self.sinks.keys())
    
    def get_sink(self, name: str) -> Optional[StorageSink]:
        """Get a specific sink by name."""
        return self.sinks.get(name)