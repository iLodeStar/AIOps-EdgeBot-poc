"""Reliability components for storage sinks: retries, circuit breakers, and queuing."""

import asyncio
import json
import random
import sqlite3
import time
from enum import Enum
from pathlib import Path
from typing import Dict, Any, List, Optional, Callable, Awaitable
import structlog
import httpx

from ..metrics import (
    mship_sink_retry_total,
    mship_sink_error_total,
    mship_sink_timeout_total,
    mship_sink_circuit_state,
    mship_sink_circuit_open_total,
    mship_sink_queue_size,
    mship_sink_queue_bytes,
    mship_sink_dlq_total,
)

logger = structlog.get_logger(__name__)


class CircuitBreakerState(Enum):
    """Circuit breaker states."""

    CLOSED = 0
    OPEN = 1
    HALF_OPEN = 2


class RetryableException(Exception):
    """Exception that indicates an operation should be retried."""

    def __init__(self, message: str, retry_after: Optional[float] = None):
        super().__init__(message)
        self.retry_after = retry_after


class NonRetryableException(Exception):
    """Exception that indicates an operation should not be retried."""

    pass


def should_retry_response(response: httpx.Response) -> bool:
    """Determine if an HTTP response should trigger a retry."""
    # Retry on 5xx server errors
    if 500 <= response.status_code < 600:
        return True

    # Retry on 429 Too Many Requests
    if response.status_code == 429:
        return True

    # Retry on certain 4xx that might be transient
    if response.status_code in (
        408,
        423,
        503,
    ):  # Request timeout, locked, service unavailable
        return True

    return False


def get_retry_after(response: httpx.Response) -> Optional[float]:
    """Extract Retry-After header value in seconds."""
    retry_after = response.headers.get("retry-after")
    if retry_after:
        try:
            # Can be in seconds or HTTP date format
            return float(retry_after)
        except ValueError:
            # If not a number, could be HTTP date - for now just return None
            pass
    return None


class SinkRetryManager:
    """Manages retry logic with exponential backoff and jitter for a sink."""

    def __init__(self, sink_name: str, config: Dict[str, Any]):
        self.sink_name = sink_name
        self.max_retries = config.get("max_retries", 3)
        self.initial_backoff_ms = config.get("initial_backoff_ms", 1000)
        self.max_backoff_ms = config.get("max_backoff_ms", 60000)
        self.jitter_factor = config.get("jitter_factor", 0.1)
        # Reduce default timeout from 30s to 10s for better responsiveness
        # This prevents long waits during database connectivity issues
        self.timeout_ms = config.get("timeout_ms", 10000)

    def calculate_backoff(
        self, attempt: int, retry_after: Optional[float] = None
    ) -> float:
        """Calculate backoff time in seconds for given attempt."""
        if retry_after:
            # Respect server's Retry-After header
            return retry_after

        # Exponential backoff: initial * (2 ^ attempt)
        backoff_ms = min(self.initial_backoff_ms * (2**attempt), self.max_backoff_ms)

        # Add jitter to avoid thundering herd
        jitter = backoff_ms * self.jitter_factor * random.random()
        total_backoff_ms = backoff_ms + jitter

        return total_backoff_ms / 1000.0  # Convert to seconds

    async def execute_with_retry(
        self, operation: Callable[[], Awaitable[Any]], events: List[Dict[str, Any]]
    ) -> Any:
        """Execute operation with retry logic."""
        last_exception = None

        for attempt in range(self.max_retries + 1):  # 0-indexed, so +1
            try:
                # Set timeout for the operation
                return await asyncio.wait_for(
                    operation(), timeout=self.timeout_ms / 1000.0
                )

            except asyncio.TimeoutError as e:
                last_exception = e
                mship_sink_timeout_total.labels(sink=self.sink_name).inc()
                logger.warning(
                    "Sink operation timed out", sink=self.sink_name, attempt=attempt + 1
                )

            except httpx.HTTPStatusError as e:
                last_exception = e
                mship_sink_error_total.labels(sink=self.sink_name).inc()

                if not should_retry_response(e.response):
                    # Non-retryable error
                    logger.error(
                        "Non-retryable HTTP error",
                        sink=self.sink_name,
                        status=e.response.status_code,
                    )
                    raise NonRetryableException(f"HTTP {e.response.status_code}: {e}")

                retry_after = get_retry_after(e.response)
                logger.warning(
                    "Retryable HTTP error",
                    sink=self.sink_name,
                    status=e.response.status_code,
                    attempt=attempt + 1,
                    retry_after=retry_after,
                )

            except (
                httpx.ConnectError,
                httpx.TimeoutException,
                httpx.NetworkError,
            ) as e:
                last_exception = e
                mship_sink_error_total.labels(sink=self.sink_name).inc()
                logger.warning(
                    "Network error",
                    sink=self.sink_name,
                    error=str(e),
                    attempt=attempt + 1,
                )

            except Exception as e:
                last_exception = e
                mship_sink_error_total.labels(sink=self.sink_name).inc()
                logger.error(
                    "Unexpected error",
                    sink=self.sink_name,
                    error=str(e),
                    attempt=attempt + 1,
                )
                # Don't retry unexpected errors
                raise NonRetryableException(f"Unexpected error: {e}")

            # If we get here, we need to retry (unless max attempts reached)
            if attempt < self.max_retries:
                mship_sink_retry_total.labels(sink=self.sink_name).inc()

                # Calculate backoff with jitter
                retry_after = (
                    getattr(last_exception, "retry_after", None)
                    if hasattr(last_exception, "response")
                    else None
                )
                backoff_seconds = self.calculate_backoff(attempt, retry_after)

                logger.info(
                    "Retrying operation",
                    sink=self.sink_name,
                    attempt=attempt + 1,
                    backoff_seconds=backoff_seconds,
                )

                await asyncio.sleep(backoff_seconds)

        # All retries exhausted
        logger.error(
            "All retry attempts exhausted",
            sink=self.sink_name,
            attempts=self.max_retries + 1,
        )
        if last_exception:
            raise last_exception
        else:
            raise Exception("All retry attempts failed")


class SinkCircuitBreaker:
    """Circuit breaker for a sink to prevent cascading failures."""

    def __init__(self, sink_name: str, config: Dict[str, Any]):
        self.sink_name = sink_name
        self.failure_threshold = config.get("failure_threshold", 5)
        self.open_duration_sec = config.get("open_duration_sec", 60)
        self.half_open_max_inflight = config.get("half_open_max_inflight", 2)

        # State
        self._state = CircuitBreakerState.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0
        self._inflight_requests = 0
        self._lock = asyncio.Lock()

        # Update metric
        mship_sink_circuit_state.labels(sink=self.sink_name).set(self._state.value)

    @property
    def state(self) -> CircuitBreakerState:
        return self._state

    async def is_call_permitted(self) -> bool:
        """Check if a call is permitted based on circuit breaker state."""
        async with self._lock:
            current_time = time.time()

            if self._state == CircuitBreakerState.CLOSED:
                return True
            elif self._state == CircuitBreakerState.OPEN:
                # Check if we should transition to half-open
                if current_time - self._last_failure_time >= self.open_duration_sec:
                    self._state = CircuitBreakerState.HALF_OPEN
                    mship_sink_circuit_state.labels(sink=self.sink_name).set(
                        self._state.value
                    )
                    logger.info(
                        "Circuit breaker transitioning to half-open",
                        sink=self.sink_name,
                    )
                    return self._inflight_requests < self.half_open_max_inflight
                else:
                    return False
            elif self._state == CircuitBreakerState.HALF_OPEN:
                return self._inflight_requests < self.half_open_max_inflight

        return False

    async def record_success(self):
        """Record a successful operation."""
        async with self._lock:
            if self._inflight_requests > 0:
                self._inflight_requests -= 1

            if self._state == CircuitBreakerState.HALF_OPEN:
                # Transition back to closed
                self._state = CircuitBreakerState.CLOSED
                self._failure_count = 0
                mship_sink_circuit_state.labels(sink=self.sink_name).set(
                    self._state.value
                )
                logger.info("Circuit breaker reset to closed", sink=self.sink_name)

    async def record_failure(self):
        """Record a failed operation."""
        async with self._lock:
            if self._inflight_requests > 0:
                self._inflight_requests -= 1

            self._failure_count += 1
            self._last_failure_time = time.time()

            if (
                self._state == CircuitBreakerState.CLOSED
                and self._failure_count >= self.failure_threshold
            ):
                self._state = CircuitBreakerState.OPEN
                mship_sink_circuit_open_total.labels(sink=self.sink_name).inc()
                mship_sink_circuit_state.labels(sink=self.sink_name).set(
                    self._state.value
                )
                logger.warning(
                    "Circuit breaker opened",
                    sink=self.sink_name,
                    failure_count=self._failure_count,
                )
            elif self._state == CircuitBreakerState.HALF_OPEN:
                # Go back to open
                self._state = CircuitBreakerState.OPEN
                mship_sink_circuit_open_total.labels(sink=self.sink_name).inc()
                mship_sink_circuit_state.labels(sink=self.sink_name).set(
                    self._state.value
                )
                logger.warning(
                    "Circuit breaker re-opened from half-open", sink=self.sink_name
                )

    async def execute_call(self):
        """Mark the start of a call (increment inflight counter)."""
        if await self.is_call_permitted():
            async with self._lock:
                self._inflight_requests += 1
            return True
        else:
            return False

    def get_stats(self) -> Dict[str, Any]:
        """Get circuit breaker statistics."""
        return {
            "state": self._state.name.lower(),
            "failure_count": self._failure_count,
            "inflight_requests": self._inflight_requests,
            "last_failure_time": self._last_failure_time,
        }


class SinkPersistentQueue:
    """SQLite-backed persistent queue for store-and-forward capability."""

    def __init__(self, sink_name: str, config: Dict[str, Any]):
        self.sink_name = sink_name
        self.queue_dir = Path(config.get("queue_dir", "./queues"))
        self.max_bytes = config.get(
            "queue_max_bytes", 100 * 1024 * 1024
        )  # 100MB default
        self.flush_interval_ms = config.get("queue_flush_interval_ms", 5000)
        self.dlq_dir = Path(config.get("dlq_dir", "./dlq"))

        # Create directories
        self.queue_dir.mkdir(parents=True, exist_ok=True)
        self.dlq_dir.mkdir(parents=True, exist_ok=True)

        # SQLite database path
        self.db_path = self.queue_dir / f"{sink_name}.db"
        self.dlq_path = self.dlq_dir / f"{sink_name}_dlq.db"

        # Initialize database
        self._init_database()

    def _init_database(self):
        """Initialize SQLite database with required tables."""
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    event_data TEXT NOT NULL,
                    retry_count INTEGER DEFAULT 0,
                    last_retry_at TIMESTAMP
                )
            """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_created_at ON queue(created_at)"
            )

        # DLQ database
        with sqlite3.connect(str(self.dlq_path)) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS dlq (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    event_data TEXT NOT NULL,
                    error_reason TEXT,
                    retry_count INTEGER
                )
            """
            )

    async def enqueue(self, events: List[Dict[str, Any]]) -> bool:
        """Add events to the persistent queue."""
        if not events:
            return True

        # Check current queue size
        current_bytes = await self._get_queue_size_bytes()

        # Estimate size of new events
        estimated_bytes = sum(
            len(json.dumps(event).encode("utf-8")) for event in events
        )

        if current_bytes + estimated_bytes > self.max_bytes:
            logger.warning(
                "Queue size limit exceeded, rejecting events",
                sink=self.sink_name,
                current_bytes=current_bytes,
                estimated_bytes=estimated_bytes,
                max_bytes=self.max_bytes,
            )
            return False

        # Insert events
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                for event in events:
                    event_json = json.dumps(event)
                    conn.execute(
                        "INSERT INTO queue (event_data) VALUES (?)", (event_json,)
                    )
                conn.commit()

            # Update metrics
            count, bytes_size = await self._get_queue_metrics()
            mship_sink_queue_size.labels(sink=self.sink_name).set(count)
            mship_sink_queue_bytes.labels(sink=self.sink_name).set(bytes_size)

            logger.debug("Events enqueued", sink=self.sink_name, count=len(events))
            return True

        except Exception as e:
            logger.error("Failed to enqueue events", sink=self.sink_name, error=str(e))
            return False

    async def dequeue(self, batch_size: int = 100) -> List[Dict[str, Any]]:
        """Get a batch of events from the queue for processing."""
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                cursor = conn.execute(
                    "SELECT id, event_data FROM queue ORDER BY created_at LIMIT ?",
                    (batch_size,),
                )
                rows = cursor.fetchall()

                events = []
                event_ids = []
                for row_id, event_json in rows:
                    try:
                        event = json.loads(event_json)
                        event["_queue_id"] = row_id  # Add internal ID for tracking
                        events.append(event)
                        event_ids.append(row_id)
                    except json.JSONDecodeError as e:
                        logger.error(
                            "Failed to parse queued event",
                            sink=self.sink_name,
                            row_id=row_id,
                            error=str(e),
                        )
                        # Move malformed events to DLQ
                        await self._move_to_dlq(
                            row_id, event_json, f"JSON decode error: {e}"
                        )

                return events

        except Exception as e:
            logger.error("Failed to dequeue events", sink=self.sink_name, error=str(e))
            return []

    async def ack_events(self, events: List[Dict[str, Any]]):
        """Acknowledge successful processing of events (remove from queue)."""
        event_ids = [event.get("_queue_id") for event in events if "_queue_id" in event]
        if not event_ids:
            return

        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                placeholders = ",".join("?" * len(event_ids))
                conn.execute(
                    f"DELETE FROM queue WHERE id IN ({placeholders})", event_ids
                )
                conn.commit()

            # Update metrics
            count, bytes_size = await self._get_queue_metrics()
            mship_sink_queue_size.labels(sink=self.sink_name).set(count)
            mship_sink_queue_bytes.labels(sink=self.sink_name).set(bytes_size)

            logger.debug(
                "Events acknowledged and removed from queue",
                sink=self.sink_name,
                count=len(event_ids),
            )

        except Exception as e:
            logger.error("Failed to ack events", sink=self.sink_name, error=str(e))

    async def nack_events(self, events: List[Dict[str, Any]], max_retries: int = 3):
        """Handle failed processing of events (increment retry count or move to DLQ)."""
        for event in events:
            queue_id = event.get("_queue_id")
            if not queue_id:
                continue

            try:
                with sqlite3.connect(str(self.db_path)) as conn:
                    cursor = conn.execute(
                        "SELECT retry_count FROM queue WHERE id = ?", (queue_id,)
                    )
                    row = cursor.fetchone()
                    if not row:
                        continue

                    retry_count = row[0] + 1

                    if retry_count > max_retries:
                        # Move to DLQ
                        await self._move_to_dlq(
                            queue_id, json.dumps(event), "Max retries exceeded"
                        )
                    else:
                        # Increment retry count
                        conn.execute(
                            "UPDATE queue SET retry_count = ?, last_retry_at = CURRENT_TIMESTAMP WHERE id = ?",
                            (retry_count, queue_id),
                        )
                    conn.commit()

            except Exception as e:
                logger.error(
                    "Failed to nack event",
                    sink=self.sink_name,
                    queue_id=queue_id,
                    error=str(e),
                )

    async def _move_to_dlq(self, queue_id: int, event_data: str, error_reason: str):
        """Move an event to the dead letter queue."""
        try:
            with sqlite3.connect(str(self.dlq_path)) as dlq_conn:
                dlq_conn.execute(
                    "INSERT INTO dlq (event_data, error_reason, retry_count) VALUES (?, ?, ?)",
                    (event_data, error_reason, 0),
                )
                dlq_conn.commit()

            # Remove from main queue
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.execute("DELETE FROM queue WHERE id = ?", (queue_id,))
                conn.commit()

            mship_sink_dlq_total.labels(sink=self.sink_name).inc()
            logger.warning(
                "Event moved to DLQ",
                sink=self.sink_name,
                queue_id=queue_id,
                reason=error_reason,
            )

        except Exception as e:
            logger.error(
                "Failed to move event to DLQ",
                sink=self.sink_name,
                queue_id=queue_id,
                error=str(e),
            )

    async def _get_queue_metrics(self) -> tuple[int, int]:
        """Get current queue count and size in bytes."""
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                cursor = conn.execute(
                    "SELECT COUNT(*), SUM(LENGTH(event_data)) FROM queue"
                )
                row = cursor.fetchone()
                count = row[0] if row[0] else 0
                bytes_size = row[1] if row[1] else 0
                return count, bytes_size
        except Exception:
            return 0, 0

    async def _get_queue_size_bytes(self) -> int:
        """Get current queue size in bytes."""
        _, bytes_size = await self._get_queue_metrics()
        return bytes_size

    def get_stats(self) -> Dict[str, Any]:
        """Get queue statistics."""
        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                cursor = conn.execute(
                    "SELECT COUNT(*), SUM(LENGTH(event_data)) FROM queue"
                )
                row = cursor.fetchone()
                queue_count = row[0] if row[0] else 0
                queue_bytes = row[1] if row[1] else 0

            with sqlite3.connect(str(self.dlq_path)) as conn:
                cursor = conn.execute("SELECT COUNT(*) FROM dlq")
                row = cursor.fetchone()
                dlq_count = row[0] if row[0] else 0

            return {
                "queue_count": queue_count,
                "queue_bytes": queue_bytes,
                "dlq_count": dlq_count,
                "max_bytes": self.max_bytes,
            }
        except Exception as e:
            logger.error("Failed to get queue stats", sink=self.sink_name, error=str(e))
            return {
                "queue_count": 0,
                "queue_bytes": 0,
                "dlq_count": 0,
                "max_bytes": self.max_bytes,
            }
