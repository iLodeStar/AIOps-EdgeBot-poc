"""Resilient wrapper for storage sinks with retry, circuit breaker, and queuing."""

import asyncio
from typing import Dict, Any, List, Optional
import structlog

from .protocols import StorageSink
from .reliability import (
    SinkRetryManager,
    SinkCircuitBreaker,
    SinkPersistentQueue,
    RetryableException,
    NonRetryableException,
)

logger = structlog.get_logger(__name__)


class ResilientSink:
    """Wrapper that adds retry, circuit breaker, and queuing to any storage sink."""

    def __init__(self, name: str, wrapped_sink: StorageSink, config: Dict[str, Any]):
        self.name = name
        self.wrapped_sink = wrapped_sink
        self.config = config

        # Initialize reliability components based on configuration
        retry_config = config.get("retry", {})
        circuit_config = config.get("circuit_breaker", {})
        queue_config = config.get("queue", {})

        self.retry_manager = (
            SinkRetryManager(name, retry_config)
            if retry_config.get("enabled", True)
            else None
        )
        self.circuit_breaker = (
            SinkCircuitBreaker(name, circuit_config)
            if circuit_config.get("enabled", True)
            else None
        )
        self.persistent_queue = (
            SinkPersistentQueue(name, queue_config)
            if queue_config.get("enabled", False)
            else None
        )

        # Background task for queue processing
        self._queue_processor_task: Optional[asyncio.Task] = None
        self._shutdown = False

    async def start(self) -> None:
        """Start the wrapped sink and queue processor."""
        await self.wrapped_sink.start()

        if self.persistent_queue:
            # Start background queue processor
            self._queue_processor_task = asyncio.create_task(self._process_queue())
            logger.info("Started queue processor", sink=self.name)

    async def stop(self) -> None:
        """Stop the wrapped sink and queue processor."""
        self._shutdown = True

        if self._queue_processor_task:
            self._queue_processor_task.cancel()
            try:
                await self._queue_processor_task
            except asyncio.CancelledError:
                pass
            logger.info("Stopped queue processor", sink=self.name)

        await self.wrapped_sink.stop()

    async def write_events(self, events: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Write events with retry, circuit breaker, and queuing."""
        if not events:
            return {"written": 0, "errors": 0, "retries": 0, "queued": 0}

        # Check circuit breaker first
        if self.circuit_breaker and not await self.circuit_breaker.is_call_permitted():
            logger.warning("Circuit breaker open, queuing events", sink=self.name)
            if self.persistent_queue:
                queued = await self._queue_events(events)
                return {"written": 0, "errors": 0, "retries": 0, "queued": queued}
            else:
                # No queue available, return as errors
                return {"written": 0, "errors": len(events), "retries": 0, "queued": 0}

        # Try direct write with retry logic
        try:
            if self.circuit_breaker:
                if not await self.circuit_breaker.execute_call():
                    # Circuit breaker rejected the call
                    if self.persistent_queue:
                        queued = await self._queue_events(events)
                        return {
                            "written": 0,
                            "errors": 0,
                            "retries": 0,
                            "queued": queued,
                        }
                    else:
                        return {
                            "written": 0,
                            "errors": len(events),
                            "retries": 0,
                            "queued": 0,
                        }

            # Execute with retry if configured
            if self.retry_manager:
                result = await self.retry_manager.execute_with_retry(
                    lambda: self.wrapped_sink.write_events(events), events
                )
            else:
                result = await self.wrapped_sink.write_events(events)

            # Record success with circuit breaker
            if self.circuit_breaker:
                await self.circuit_breaker.record_success()

            # Ensure result has all required fields
            if isinstance(result, dict):
                return {
                    "written": result.get("written", 0),
                    "errors": result.get("errors", 0),
                    "retries": result.get("retries", 0),
                    "queued": 0,
                }
            else:
                # Fallback for sinks that don't return proper stats
                return {"written": len(events), "errors": 0, "retries": 0, "queued": 0}

        except NonRetryableException as e:
            # Record failure and don't queue
            if self.circuit_breaker:
                await self.circuit_breaker.record_failure()
            logger.error(
                "Non-retryable error, not queuing", sink=self.name, error=str(e)
            )
            return {"written": 0, "errors": len(events), "retries": 0, "queued": 0}

        except Exception as e:
            # Record failure with circuit breaker
            if self.circuit_breaker:
                await self.circuit_breaker.record_failure()

            # Queue events if available
            if self.persistent_queue:
                logger.warning(
                    "Direct write failed, queuing events", sink=self.name, error=str(e)
                )
                queued = await self._queue_events(events)
                return {"written": 0, "errors": 0, "retries": 0, "queued": queued}
            else:
                logger.error(
                    "Direct write failed, no queue available",
                    sink=self.name,
                    error=str(e),
                )
                return {"written": 0, "errors": len(events), "retries": 0, "queued": 0}

    async def _queue_events(self, events: List[Dict[str, Any]]) -> int:
        """Queue events for later processing."""
        if not self.persistent_queue:
            return 0

        success = await self.persistent_queue.enqueue(events)
        return len(events) if success else 0

    async def _process_queue(self):
        """Background task to process queued events."""
        if not self.persistent_queue:
            return

        flush_interval = self.persistent_queue.flush_interval_ms / 1000.0

        while not self._shutdown:
            try:
                # Check if circuit breaker allows processing
                if (
                    self.circuit_breaker
                    and not await self.circuit_breaker.is_call_permitted()
                ):
                    await asyncio.sleep(flush_interval)
                    continue

                # Get batch of events from queue
                batch = await self.persistent_queue.dequeue(batch_size=100)
                if not batch:
                    await asyncio.sleep(flush_interval)
                    continue

                logger.debug(
                    "Processing queued events", sink=self.name, count=len(batch)
                )

                # Attempt to write the batch
                try:
                    if self.circuit_breaker:
                        if not await self.circuit_breaker.execute_call():
                            # Circuit breaker rejected, wait and try again later
                            await asyncio.sleep(flush_interval)
                            continue

                    # Try to write with retry
                    if self.retry_manager:
                        result = await self.retry_manager.execute_with_retry(
                            lambda: self.wrapped_sink.write_events(batch), batch
                        )
                    else:
                        result = await self.wrapped_sink.write_events(batch)

                    # Success - acknowledge events
                    if self.circuit_breaker:
                        await self.circuit_breaker.record_success()
                    await self.persistent_queue.ack_events(batch)

                    logger.debug(
                        "Successfully processed queued events",
                        sink=self.name,
                        count=len(batch),
                    )

                except NonRetryableException as e:
                    # Non-retryable error - nack events (may go to DLQ)
                    if self.circuit_breaker:
                        await self.circuit_breaker.record_failure()
                    await self.persistent_queue.nack_events(
                        batch, max_retries=0
                    )  # Immediate DLQ
                    logger.error(
                        "Non-retryable error processing queue",
                        sink=self.name,
                        error=str(e),
                    )

                except Exception as e:
                    # Retryable error - nack events for retry
                    if self.circuit_breaker:
                        await self.circuit_breaker.record_failure()
                    await self.persistent_queue.nack_events(batch)
                    logger.warning(
                        "Error processing queued events, will retry",
                        sink=self.name,
                        error=str(e),
                    )

            except Exception as e:
                logger.error(
                    "Unexpected error in queue processor", sink=self.name, error=str(e)
                )
                await asyncio.sleep(flush_interval)

    def is_healthy(self) -> bool:
        """Check if sink is healthy considering circuit breaker state."""
        base_healthy = self.wrapped_sink.is_healthy()

        if self.circuit_breaker:
            # Consider unhealthy if circuit breaker is open
            cb_healthy = self.circuit_breaker.state.name != "OPEN"
            return base_healthy and cb_healthy

        return base_healthy

    def get_stats(self) -> Dict[str, Any]:
        """Get comprehensive statistics including reliability components."""
        stats = {
            "base_healthy": self.wrapped_sink.is_healthy(),
            "overall_healthy": self.is_healthy(),
        }

        if self.circuit_breaker:
            stats["circuit_breaker"] = self.circuit_breaker.get_stats()

        if self.persistent_queue:
            stats["queue"] = self.persistent_queue.get_stats()

        return stats

    # Delegate other methods to wrapped sink
    async def health_check(self) -> bool:
        """Delegate health check to wrapped sink."""
        return await self.wrapped_sink.health_check()

    def is_enabled(self) -> bool:
        """Delegate enabled check to wrapped sink."""
        return self.wrapped_sink.is_enabled()

    @property
    def sink(self):
        """Backward compatibility property for tests."""
        return self.wrapped_sink

    @sink.setter
    def sink(self, value):
        """Backward compatibility setter for tests."""
        self.wrapped_sink = value
