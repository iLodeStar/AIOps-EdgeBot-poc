"""Reliability components for SATCOM-friendly operation."""

import asyncio
import time
import random
import hashlib
from typing import Dict, Any, Optional, Set, Tuple
from enum import Enum
import structlog

from .metrics import (
    mship_sink_retry_total,
    mship_sink_error_total,
    mship_sink_timeout_total,
    mship_sink_circuit_state,
    mship_sink_circuit_open_total,
)

logger = structlog.get_logger(__name__)


class CircuitState(Enum):
    """Circuit breaker states."""

    CLOSED = 0
    OPEN = 1
    HALF_OPEN = 2


class CircuitBreaker:
    """Per-sink circuit breaker with configurable thresholds."""

    def __init__(self, sink_name: str, config: Dict[str, Any]):
        self.sink_name = sink_name
        self.failure_threshold = config.get("failure_threshold", 5)
        self.open_duration_sec = config.get("open_duration_sec", 60)
        self.half_open_max_inflight = config.get("half_open_max_inflight", 1)

        # State
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time = 0
        self.opened_time = 0
        self.half_open_requests = 0

        # Update initial metric
        mship_sink_circuit_state.labels(sink=sink_name).set(self.state.value)

    def can_execute(self) -> bool:
        """Check if request can be executed based on circuit state."""
        current_time = time.time()

        if self.state == CircuitState.CLOSED:
            return True

        elif self.state == CircuitState.OPEN:
            # Check if we can transition to half-open
            if current_time - self.opened_time >= self.open_duration_sec:
                self._transition_to_half_open()
                return True
            return False

        elif self.state == CircuitState.HALF_OPEN:
            # Allow limited requests in half-open state
            return self.half_open_requests < self.half_open_max_inflight

        return False

    def record_success(self):
        """Record a successful operation."""
        if self.state == CircuitState.HALF_OPEN:
            # Successful request in half-open, reset to closed
            self._transition_to_closed()
        elif self.state == CircuitState.CLOSED:
            # Reset failure count on success
            self.failure_count = 0

    def record_failure(self):
        """Record a failed operation."""
        self.failure_count += 1
        self.last_failure_time = time.time()

        mship_sink_error_total.labels(sink=self.sink_name).inc()

        if self.state == CircuitState.CLOSED:
            if self.failure_count >= self.failure_threshold:
                self._transition_to_open()
        elif self.state == CircuitState.HALF_OPEN:
            # Failure in half-open, go back to open
            self._transition_to_open()

    def record_timeout(self):
        """Record a timeout (treated as failure)."""
        mship_sink_timeout_total.labels(sink=self.sink_name).inc()
        self.record_failure()

    def _transition_to_open(self):
        """Transition to open state."""
        self.state = CircuitState.OPEN
        self.opened_time = time.time()
        self.half_open_requests = 0

        mship_sink_circuit_open_total.labels(sink=self.sink_name).inc()
        mship_sink_circuit_state.labels(sink=self.sink_name).set(self.state.value)

        logger.warning(
            "Circuit breaker opened",
            sink=self.sink_name,
            failure_count=self.failure_count,
            threshold=self.failure_threshold,
        )

    def _transition_to_half_open(self):
        """Transition to half-open state."""
        self.state = CircuitState.HALF_OPEN
        self.half_open_requests = 0

        mship_sink_circuit_state.labels(sink=self.sink_name).set(self.state.value)

        logger.info("Circuit breaker half-open", sink=self.sink_name)

    def _transition_to_closed(self):
        """Transition to closed state."""
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.half_open_requests = 0

        mship_sink_circuit_state.labels(sink=self.sink_name).set(self.state.value)

        logger.info("Circuit breaker closed", sink=self.sink_name)

    def get_state_info(self) -> Dict[str, Any]:
        """Get current state information."""
        return {
            "state": self.state.name,
            "failure_count": self.failure_count,
            "failure_threshold": self.failure_threshold,
            "last_failure_time": self.last_failure_time,
            "opened_time": (
                self.opened_time if self.state == CircuitState.OPEN else None
            ),
            "half_open_requests": (
                self.half_open_requests
                if self.state == CircuitState.HALF_OPEN
                else None
            ),
        }


class RetryManager:
    """Enhanced retry manager with jittered exponential backoff."""

    def __init__(self, sink_name: str, config: Dict[str, Any]):
        self.sink_name = sink_name
        self.max_retries = config.get("max_retries", 5)
        self.initial_backoff_ms = config.get("initial_backoff_ms", 500)
        self.max_backoff_ms = config.get("max_backoff_ms", 30000)
        self.jitter_factor = config.get("jitter_factor", 0.2)
        self.timeout_ms = config.get("timeout_ms", 5000)

    def should_retry(self, attempt: int, exception: Exception) -> bool:
        """Check if we should retry based on attempt count and exception type."""
        if attempt >= self.max_retries:
            return False

        # Don't retry on client errors (4xx) except 429
        if hasattr(exception, "response"):
            status_code = getattr(exception.response, "status_code", None)
            if status_code:
                if 400 <= status_code < 500:
                    # Only retry on 429 (rate limiting)
                    return status_code == 429
                # Retry on 5xx server errors
                return status_code >= 500

        # Retry on timeouts and connection errors
        return True

    def calculate_backoff(self, attempt: int) -> float:
        """Calculate backoff time with jittered exponential backoff."""
        # Exponential backoff: initial * (2 ^ attempt)
        backoff_ms = min(self.initial_backoff_ms * (2**attempt), self.max_backoff_ms)

        # Add jitter to avoid thundering herd
        if self.jitter_factor > 0:
            jitter_range = backoff_ms * self.jitter_factor
            jitter = random.uniform(-jitter_range, jitter_range)
            backoff_ms = max(0, backoff_ms + jitter)

        return backoff_ms / 1000.0  # Convert to seconds

    def get_retry_after_delay(
        self, response_headers: Dict[str, str]
    ) -> Optional[float]:
        """Extract retry-after delay from response headers."""
        retry_after = response_headers.get("retry-after") or response_headers.get(
            "Retry-After"
        )
        if not retry_after:
            return None

        try:
            # Try parsing as seconds
            return float(retry_after)
        except ValueError:
            try:
                # Try parsing as HTTP date (not implemented for simplicity)
                # In a full implementation, you'd parse HTTP date format
                return None
            except:
                return None

    async def execute_with_retry(self, operation, *args, **kwargs):
        """Execute operation with retry logic."""
        for attempt in range(self.max_retries + 1):
            try:
                if attempt > 0:
                    mship_sink_retry_total.labels(sink=self.sink_name).inc()

                return await operation(*args, **kwargs)

            except Exception as e:
                if not self.should_retry(attempt, e):
                    raise

                if attempt < self.max_retries:
                    # Check for Retry-After header if available
                    retry_delay = None
                    if hasattr(e, "response") and hasattr(e.response, "headers"):
                        retry_delay = self.get_retry_after_delay(
                            dict(e.response.headers)
                        )

                    if retry_delay is None:
                        retry_delay = self.calculate_backoff(attempt)

                    logger.info(
                        "Retrying operation",
                        sink=self.sink_name,
                        attempt=attempt + 1,
                        delay=retry_delay,
                        error=str(e),
                    )

                    await asyncio.sleep(retry_delay)
                else:
                    raise


class IdempotencyManager:
    """Manages idempotency keys and deduplication."""

    def __init__(self, config: Dict[str, Any]):
        self.window_sec = config.get("window_sec", 3600)  # 1 hour default
        self._seen_keys: Dict[str, float] = {}  # key -> timestamp

    def generate_batch_key(self, batch: list) -> str:
        """Generate idempotency key for a batch."""
        # Create a deterministic hash of the batch content
        batch_str = str(
            sorted(
                [
                    str(item.get("message", "")) + str(item.get("timestamp", ""))
                    for item in batch
                ]
            )
        )
        return hashlib.md5(batch_str.encode()).hexdigest()

    def is_duplicate(self, key: str) -> bool:
        """Check if this key was seen recently."""
        current_time = time.time()

        # Clean expired keys
        self._clean_expired_keys(current_time)

        # Check if key exists
        if key in self._seen_keys:
            return True

        # Record this key
        self._seen_keys[key] = current_time
        return False

    def _clean_expired_keys(self, current_time: float):
        """Remove expired keys from the cache."""
        cutoff_time = current_time - self.window_sec
        expired_keys = [
            key for key, timestamp in self._seen_keys.items() if timestamp < cutoff_time
        ]
        for key in expired_keys:
            del self._seen_keys[key]

    def get_stats(self) -> Dict[str, Any]:
        """Get idempotency manager statistics."""
        return {"cached_keys": len(self._seen_keys), "window_sec": self.window_sec}
