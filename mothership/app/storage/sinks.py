"""Storage sinks manager for dual writes to TimescaleDB and Loki."""

import asyncio
from typing import Dict, Any, List, Optional, Protocol
from abc import ABC, abstractmethod
import structlog

from .loki import LokiClient
from .reliability import (
    SinkRetryManager, SinkCircuitBreaker, PersistentQueue, IdempotencyManager,
    RetryConfig, CircuitBreakerConfig
)
from ..metrics import mship_sink_write_seconds, mship_sink_retry_total

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


class ReliableSinkWrapper:
    """Wrapper that adds reliability features to any StorageSink."""
    
    def __init__(self, name: str, sink: StorageSink, config: Dict[str, Any]):
        self.name = name
        self.sink = sink
        self.config = config
        
        # Create reliability components
        reliability_config = config.get('reliability', {})
        
        self.retry_manager = SinkRetryManager(
            name, 
            RetryConfig(
                max_retries=reliability_config.get('max_retries', 5),
                initial_backoff_ms=reliability_config.get('initial_backoff_ms', 500),
                max_backoff_ms=reliability_config.get('max_backoff_ms', 30000),
                jitter_factor=reliability_config.get('jitter_factor', 0.2),
                timeout_ms=reliability_config.get('timeout_ms', 5000)
            )
        )
        
        self.circuit_breaker = SinkCircuitBreaker(
            name,
            CircuitBreakerConfig(
                failure_threshold=reliability_config.get('failure_threshold', 5),
                open_duration_sec=reliability_config.get('open_duration_sec', 60),
                half_open_max_inflight=reliability_config.get('half_open_max_inflight', 3)
            )
        )
    
    async def start(self) -> None:
        """Start the underlying sink."""
        await self.sink.start()
    
    async def stop(self) -> None:
        """Stop the underlying sink."""
        await self.sink.stop()
    
    async def write_events(self, events: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Write events with retry logic and circuit breaker protection."""
        # Check circuit breaker
        if not self.circuit_breaker.can_execute():
            logger.warning("Circuit breaker open, skipping write", sink=self.name)
            return {"written": 0, "errors": len(events), "circuit_open": True}
        
        # Track inflight request for half-open state
        self.circuit_breaker.record_inflight()
        
        attempt = 0
        last_exception = None
        last_response = None
        
        while True:
            attempt += 1
            try:
                # Try to write
                result = await self.sink.write_events(events)
                
                # Success - record it
                self.circuit_breaker.record_success()
                
                if attempt > 1:
                    logger.info("Retry successful", sink=self.name, attempt=attempt-1)
                
                return result
                
            except Exception as e:
                last_exception = e
                
                # Check if we should retry
                if not self.retry_manager.should_retry(exception=e, attempt=attempt):
                    break
                
                # Calculate backoff delay
                delay = self.retry_manager.get_backoff_delay(attempt)
                
                logger.warning("Sink write failed, retrying", 
                             sink=self.name, 
                             attempt=attempt,
                             delay=delay,
                             error=str(e))
                
                mship_sink_retry_total.labels(sink=self.name).inc()
                
                await asyncio.sleep(delay)
        
        # All retries failed
        self.circuit_breaker.record_failure()
        
        logger.error("All retries exhausted", 
                   sink=self.name, 
                   attempts=attempt,
                   last_error=str(last_exception) if last_exception else "unknown")
        
        return {"written": 0, "errors": len(events)}
    
    def is_healthy(self) -> bool:
        """Check if sink is healthy (considering circuit breaker state)."""
        return self.sink.is_healthy() and self.circuit_breaker.can_execute()


class SinksManager:
    """Manages writes to multiple storage sinks with reliability features."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.sinks: Dict[str, ReliableSinkWrapper] = {}
        self.persistent_queue: Optional[PersistentQueue] = None
        self.idempotency_manager: Optional[IdempotencyManager] = None
        
        # Initialize reliability components if enabled
        reliability_config = config.get('reliability', {})
        
        if reliability_config.get('queue_enabled', False):
            self.persistent_queue = PersistentQueue(
                queue_dir=reliability_config.get('queue_dir', './data/queue'),
                max_bytes=reliability_config.get('queue_max_bytes', 1073741824),
                flush_interval_ms=reliability_config.get('queue_flush_interval_ms', 2000),
                dlq_dir=reliability_config.get('dlq_dir', './data/dlq'),
                flush_bandwidth_bytes_per_sec=reliability_config.get('flush_bandwidth_bytes_per_sec', 1048576)
            )
            
        if reliability_config.get('idempotency_window_sec'):
            self.idempotency_manager = IdempotencyManager(
                window_sec=reliability_config.get('idempotency_window_sec', 86400)
            )
        
        # Initialize sinks based on configuration
        sinks_config = config.get('sinks', {})
        
        if sinks_config.get('timescaledb', {}).get('enabled', True):
            raw_sink = TSDBSink(sinks_config.get('timescaledb', {}))
            self.sinks["tsdb"] = ReliableSinkWrapper("tsdb", raw_sink, config)
            
        if sinks_config.get('loki', {}).get('enabled', False):
            raw_sink = LokiSink(sinks_config.get('loki', {}))
            self.sinks["loki"] = ReliableSinkWrapper("loki", raw_sink, config)
    
    async def start(self):
        """Start all enabled sinks."""
        start_tasks = []
        for name, sink in self.sinks.items():
            logger.info("Starting sink", sink=name)
            start_tasks.append(sink.start())
        
        if start_tasks:
            await asyncio.gather(*start_tasks, return_exceptions=True)
        
        # Start background queue processing if enabled
        if self.persistent_queue:
            asyncio.create_task(self._process_queued_events())
        
        logger.info("SinksManager started", 
                   enabled_sinks=list(self.sinks.keys()),
                   persistent_queue=self.persistent_queue is not None)
    
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
        
        # Check for duplicates if idempotency is enabled
        if self.idempotency_manager:
            if await self.idempotency_manager.is_duplicate(events):
                logger.info("Duplicate batch detected, skipping", events=len(events))
                return {"duplicate": {"skipped": len(events)}}
        
        # Try direct writes first
        write_tasks = {}
        for name, sink in self.sinks.items():
            write_tasks[name] = asyncio.create_task(
                self._safe_write(name, sink, events)
            )
        
        # Wait for all writes to complete
        results = {}
        failed_sinks = []
        
        for name, task in write_tasks.items():
            try:
                result = await task
                results[name] = result
                
                # Check if write failed and sink has persistent queue enabled
                if result.get("errors", 0) > 0 and self.persistent_queue:
                    failed_sinks.append(name)
                    
            except Exception as e:
                logger.error("Sink write failed", sink=name, error=str(e))
                results[name] = {"written": 0, "errors": len(events)}
                if self.persistent_queue:
                    failed_sinks.append(name)
        
        # Queue failed events if persistent queue is enabled
        if failed_sinks and self.persistent_queue:
            for sink_name in failed_sinks:
                success = await self.persistent_queue.enqueue(events, sink_name)
                if success:
                    logger.info("Events queued for retry", sink=sink_name, events=len(events))
                    results[sink_name]["queued"] = len(events)
        
        # Log summary
        total_written = sum(result.get("written", 0) for result in results.values())
        total_errors = sum(result.get("errors", 0) for result in results.values())
        total_queued = sum(result.get("queued", 0) for result in results.values())
        
        logger.info("Multi-sink write completed",
                   events=len(events),
                   total_written=total_written,
                   total_errors=total_errors,
                   total_queued=total_queued,
                   sink_results=results)
        
        return results
    
    async def _safe_write(self, name: str, sink: ReliableSinkWrapper, events: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Safely write to a sink with error handling and metrics observation."""
        try:
            # Observe per-sink write latency as required
            with mship_sink_write_seconds.labels(sink=name).time():
                return await sink.write_events(events)
        except Exception as e:
            logger.error("Sink write exception", sink=name, error=str(e))
            return {"written": 0, "errors": len(events)}
    
    def get_health_status(self) -> Dict[str, Any]:
        """Get health status of all sinks."""
        sink_health = {}
        overall_healthy = True
        
        for name, sink in self.sinks.items():
            is_healthy = sink.is_healthy()
            sink_health[name] = {
                "healthy": is_healthy,
                "enabled": True
            }
            if not is_healthy:
                overall_healthy = False
        
        return {
            "healthy": overall_healthy,
            "sinks": sink_health,
            "enabled_sinks": list(self.sinks.keys())
        }
    
    def get_stats(self) -> Dict[str, Any]:
        """Get statistics from all sinks."""
        stats = {
            "enabled_sinks": list(self.sinks.keys()),
            "sink_count": len(self.sinks),
            "persistent_queue_enabled": self.persistent_queue is not None,
            "idempotency_enabled": self.idempotency_manager is not None
        }
        
        # Add queue stats if enabled
        if self.persistent_queue:
            stats["queue_stats"] = self.persistent_queue.get_stats()
            
        return stats
    
    def get_sink_names(self) -> List[str]:
        """Get names of all configured sinks."""
        return list(self.sinks.keys())
    
    def get_sink(self, name: str) -> Optional[ReliableSinkWrapper]:
        """Get a specific sink by name."""
        return self.sinks.get(name)
    
    async def _process_queued_events(self):
        """Background task to process queued events."""
        if not self.persistent_queue:
            return
            
        logger.info("Starting queued events processor")
        
        while True:
            try:
                # Get batch of queued events
                batch = await self.persistent_queue.dequeue_batch(100)
                
                if not batch:
                    # No events, wait before checking again
                    await asyncio.sleep(2.0)
                    continue
                
                processed_files = []
                
                for filename, events, sink_name in batch:
                    if sink_name in self.sinks:
                        sink = self.sinks[sink_name]
                        try:
                            result = await sink.write_events(events)
                            
                            if result.get("written", 0) > 0:
                                # Success - mark file for removal
                                processed_files.append(filename)
                                logger.info("Queued events processed successfully",
                                          sink=sink_name, events=len(events))
                            else:
                                logger.warning("Queued events failed again",
                                             sink=sink_name, events=len(events))
                                # File stays in queue for next attempt
                                
                        except Exception as e:
                            logger.error("Failed to process queued events",
                                       sink=sink_name, events=len(events), error=str(e))
                    else:
                        # Sink no longer exists, remove file
                        processed_files.append(filename)
                        logger.warning("Sink no longer exists, removing queued events",
                                     sink=sink_name, events=len(events))
                
                # Remove successfully processed files
                if processed_files:
                    await self.persistent_queue.commit_batch(processed_files)
                
                # Rate limiting based on bandwidth
                if batch:
                    reliability_config = self.config.get('reliability', {})
                    bandwidth_limit = reliability_config.get('flush_bandwidth_bytes_per_sec', 1048576)
                    
                    # Simple rate limiting - sleep for 1 second per batch
                    # TODO: Implement more sophisticated bandwidth limiting
                    await asyncio.sleep(1.0)
                    
            except Exception as e:
                logger.error("Error in queued events processor", error=str(e))
                await asyncio.sleep(5.0)  # Back off on errors