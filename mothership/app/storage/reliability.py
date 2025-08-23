"""Reliability components for storage sinks: retries, circuit breakers, persistent queue."""

import asyncio
import json
import random
import time
import os
import hashlib
from typing import Dict, Any, List, Optional, Set, Tuple
from enum import Enum
from dataclasses import dataclass
from pathlib import Path
import httpx
import structlog

from ..metrics import (
    mship_sink_retry_total,
    mship_sink_error_total,
    mship_sink_timeout_total,
    mship_sink_circuit_state,
    mship_sink_circuit_open_total,
    mship_queue_depth,
    mship_queue_bytes
)

logger = structlog.get_logger(__name__)


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = 0
    OPEN = 1
    HALF_OPEN = 2


@dataclass
class RetryConfig:
    """Configuration for retry behavior."""
    max_retries: int = 5
    initial_backoff_ms: int = 500
    max_backoff_ms: int = 30000
    jitter_factor: float = 0.2
    timeout_ms: int = 5000


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker."""
    failure_threshold: int = 5
    open_duration_sec: int = 60
    half_open_max_inflight: int = 3


class SinkRetryManager:
    """Manages retries for a sink with jittered exponential backoff."""
    
    def __init__(self, sink_name: str, config: RetryConfig):
        self.sink_name = sink_name
        self.config = config
        
    def should_retry(self, response: Optional[httpx.Response] = None, 
                    exception: Optional[Exception] = None, 
                    attempt: int = 0) -> bool:
        """Determine if we should retry based on response/exception."""
        if attempt > self.config.max_retries:  # Changed from >= to >
            return False
            
        # Retry on network/timeout exceptions
        if exception:
            if isinstance(exception, (httpx.TimeoutException, httpx.ConnectTimeout, 
                                   httpx.ReadTimeout, httpx.WriteTimeout)):
                mship_sink_timeout_total.labels(sink=self.sink_name).inc()
                return True
            if isinstance(exception, (httpx.NetworkError, ConnectionError)):
                mship_sink_error_total.labels(sink=self.sink_name).inc()
                return True
            return False
            
        # Retry on HTTP status codes
        if response:
            if response.status_code >= 500:  # 5xx errors
                mship_sink_error_total.labels(sink=self.sink_name).inc()
                return True
            if response.status_code == 429:  # Rate limited
                mship_sink_error_total.labels(sink=self.sink_name).inc()
                return True
            if response.status_code >= 400:  # Other 4xx errors - don't retry
                mship_sink_error_total.labels(sink=self.sink_name).inc()
                return False
                
        return False
    
    def get_backoff_delay(self, attempt: int, retry_after: Optional[int] = None) -> float:
        """Calculate backoff delay with jitter."""
        if retry_after is not None:
            # Honor Retry-After header - convert to float and ensure minimum
            return max(float(retry_after), 0.1)
            
        # Exponential backoff: initial * (2 ^ (attempt - 1))
        # attempt=1 should use initial backoff, attempt=2 should be 2x, etc.
        delay_ms = min(
            self.config.initial_backoff_ms * (2 ** (attempt - 1)),
            self.config.max_backoff_ms
        )
        
        # Add jitter: delay ± (jitter_factor * delay)
        jitter_range = delay_ms * self.config.jitter_factor
        jitter = random.uniform(-jitter_range, jitter_range)
        
        final_delay_ms = max(delay_ms + jitter, 100)  # Minimum 100ms
        return final_delay_ms / 1000.0  # Convert to seconds
    
    def get_retry_after(self, response: Optional[httpx.Response]) -> Optional[int]:
        """Extract Retry-After header value."""
        if response and 'retry-after' in response.headers:
            try:
                return int(response.headers['retry-after'])
            except ValueError:
                pass
        return None


class SinkCircuitBreaker:
    """Circuit breaker for a sink with closed/open/half-open states."""
    
    def __init__(self, sink_name: str, config: CircuitBreakerConfig):
        self.sink_name = sink_name
        self.config = config
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time = 0.0
        self.inflight_requests = 0
        
        # Update metrics
        mship_sink_circuit_state.labels(sink=self.sink_name).set(self.state.value)
    
    def can_execute(self) -> bool:
        """Check if execution is allowed based on circuit state."""
        current_time = time.time()
        
        if self.state == CircuitState.CLOSED:
            return True
        elif self.state == CircuitState.OPEN:
            # Check if we should transition to half-open
            if current_time - self.last_failure_time >= self.config.open_duration_sec:
                self._transition_to_half_open()
                return True
            return False
        elif self.state == CircuitState.HALF_OPEN:
            return self.inflight_requests < self.config.half_open_max_inflight
        
        return False
    
    def record_success(self):
        """Record a successful execution."""
        if self.state == CircuitState.HALF_OPEN:
            self._transition_to_closed()
        self.failure_count = 0
        if self.inflight_requests > 0:
            self.inflight_requests -= 1
    
    def record_failure(self):
        """Record a failed execution."""
        self.failure_count += 1
        self.last_failure_time = time.time()
        
        if self.inflight_requests > 0:
            self.inflight_requests -= 1
        
        if self.state == CircuitState.CLOSED:
            if self.failure_count >= self.config.failure_threshold:
                self._transition_to_open()
        elif self.state == CircuitState.HALF_OPEN:
            self._transition_to_open()
    
    def record_inflight(self):
        """Record an inflight request (for half-open state)."""
        self.inflight_requests += 1
    
    def _transition_to_open(self):
        """Transition to open state."""
        logger.warning("Circuit breaker opening", sink=self.sink_name,
                      failure_count=self.failure_count)
        self.state = CircuitState.OPEN
        mship_sink_circuit_state.labels(sink=self.sink_name).set(self.state.value)
        mship_sink_circuit_open_total.labels(sink=self.sink_name).inc()
    
    def _transition_to_half_open(self):
        """Transition to half-open state."""
        logger.info("Circuit breaker half-opening", sink=self.sink_name)
        self.state = CircuitState.HALF_OPEN
        self.inflight_requests = 0
        mship_sink_circuit_state.labels(sink=self.sink_name).set(self.state.value)
    
    def _transition_to_closed(self):
        """Transition to closed state."""
        logger.info("Circuit breaker closing", sink=self.sink_name)
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.inflight_requests = 0
        mship_sink_circuit_state.labels(sink=self.sink_name).set(self.state.value)
    
    def get_state(self) -> CircuitState:
        """Get current circuit state."""
        return self.state


class PersistentQueue:
    """Persistent on-disk queue for store-and-forward functionality."""
    
    def __init__(self, queue_dir: str, max_bytes: int, flush_interval_ms: int,
                 dlq_dir: str, flush_bandwidth_bytes_per_sec: int):
        self.queue_dir = Path(queue_dir)
        self.max_bytes = max_bytes
        self.flush_interval_ms = flush_interval_ms
        self.dlq_dir = Path(dlq_dir)
        self.flush_bandwidth_bytes_per_sec = flush_bandwidth_bytes_per_sec
        
        # Ensure directories exist
        self.queue_dir.mkdir(parents=True, exist_ok=True)
        self.dlq_dir.mkdir(parents=True, exist_ok=True)
        
        self._current_size_bytes = 0
        self._sequence = 0
        self._lock = asyncio.Lock()
        
        # Calculate current size
        self._calculate_current_size()
        
    def _calculate_current_size(self):
        """Calculate current queue size."""
        total_size = 0
        for file_path in self.queue_dir.glob("*.json"):
            try:
                total_size += file_path.stat().st_size
            except OSError:
                pass
        
        self._current_size_bytes = total_size
        mship_queue_bytes.set(self._current_size_bytes)
        
        # Count files for depth metric
        file_count = len(list(self.queue_dir.glob("*.json")))
        mship_queue_depth.set(file_count)
    
    async def enqueue(self, events: List[Dict[str, Any]], sink_name: str) -> bool:
        """Enqueue events for later processing."""
        async with self._lock:
            # Check if we have space
            event_data = json.dumps({"events": events, "sink": sink_name, 
                                   "timestamp": time.time()})
            event_size = len(event_data.encode('utf-8'))
            
            if self._current_size_bytes + event_size > self.max_bytes:
                logger.warning("Queue full, rejecting events", 
                             current_bytes=self._current_size_bytes,
                             max_bytes=self.max_bytes,
                             event_size=event_size)
                return False
            
            # Write to file
            self._sequence += 1
            filename = f"{int(time.time())}_{self._sequence:06d}.json"
            file_path = self.queue_dir / filename
            
            try:
                with open(file_path, 'w') as f:
                    f.write(event_data)
                
                self._current_size_bytes += event_size
                mship_queue_bytes.set(self._current_size_bytes)
                mship_queue_depth.inc()
                
                logger.debug("Events queued", file=filename, events=len(events),
                           bytes=event_size)
                return True
                
            except Exception as e:
                logger.error("Failed to enqueue events", error=str(e))
                return False
    
    async def dequeue_batch(self, max_events: int = 100) -> List[Tuple[str, List[Dict[str, Any]], str]]:
        """Dequeue a batch of events. Returns list of (filename, events, sink_name)."""
        async with self._lock:
            batch = []
            total_events = 0
            
            # Get oldest files first
            files = sorted(self.queue_dir.glob("*.json"))
            
            for file_path in files:
                if total_events >= max_events:
                    break
                    
                try:
                    with open(file_path, 'r') as f:
                        data = json.load(f)
                    
                    events = data.get("events", [])
                    sink_name = data.get("sink", "unknown")
                    
                    batch.append((file_path.name, events, sink_name))
                    total_events += len(events)
                    
                except Exception as e:
                    logger.error("Failed to read queued file", file=file_path.name,
                               error=str(e))
                    # Move to DLQ
                    await self._move_to_dlq(file_path, str(e))
            
            return batch
    
    async def commit_batch(self, filenames: List[str]):
        """Remove successfully processed files."""
        async with self._lock:
            for filename in filenames:
                file_path = self.queue_dir / filename
                try:
                    if file_path.exists():
                        file_size = file_path.stat().st_size
                        file_path.unlink()
                        self._current_size_bytes -= file_size
                        mship_queue_bytes.set(self._current_size_bytes)
                        mship_queue_depth.dec()
                        
                except Exception as e:
                    logger.error("Failed to remove processed file", file=filename,
                               error=str(e))
    
    async def _move_to_dlq(self, file_path: Path, error_reason: str):
        """Move a file to dead letter queue."""
        try:
            dlq_path = self.dlq_dir / f"{file_path.name}.error"
            
            # Add error metadata
            error_data = {
                "original_file": file_path.name,
                "error_reason": error_reason,
                "error_timestamp": time.time()
            }
            
            with open(dlq_path, 'w') as f:
                json.dump(error_data, f)
            
            # Remove original file
            if file_path.exists():
                file_size = file_path.stat().st_size
                file_path.unlink()
                self._current_size_bytes -= file_size
                mship_queue_bytes.set(self._current_size_bytes)
                mship_queue_depth.dec()
            
            logger.warning("File moved to DLQ", file=file_path.name, 
                         reason=error_reason)
            
        except Exception as e:
            logger.error("Failed to move file to DLQ", file=file_path.name,
                       error=str(e))
    
    def get_stats(self) -> Dict[str, Any]:
        """Get queue statistics."""
        return {
            "current_bytes": self._current_size_bytes,
            "max_bytes": self.max_bytes,
            "utilization": self._current_size_bytes / self.max_bytes,
            "file_count": len(list(self.queue_dir.glob("*.json"))),
            "dlq_count": len(list(self.dlq_dir.glob("*.error")))
        }


class IdempotencyManager:
    """Manages idempotency keys to prevent duplicate processing."""
    
    def __init__(self, window_sec: int = 86400):
        self.window_sec = window_sec
        self._seen_keys: Dict[str, float] = {}
        self._lock = asyncio.Lock()
    
    async def is_duplicate(self, events: List[Dict[str, Any]]) -> bool:
        """Check if this batch of events is a duplicate."""
        batch_key = self._generate_batch_key(events)
        current_time = time.time()
        
        async with self._lock:
            # Clean old entries
            cutoff_time = current_time - self.window_sec
            self._seen_keys = {k: v for k, v in self._seen_keys.items() 
                             if v > cutoff_time}
            
            # Check for duplicate
            if batch_key in self._seen_keys:
                return True
            
            # Record this batch
            self._seen_keys[batch_key] = current_time
            return False
    
    def _generate_batch_key(self, events: List[Dict[str, Any]]) -> str:
        """Generate a deterministic key for a batch of events."""
        # Create a hash of the event content
        content = json.dumps(events, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(content.encode('utf-8')).hexdigest()[:16]