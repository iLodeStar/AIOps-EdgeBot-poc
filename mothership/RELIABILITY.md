# Reliability Features for Storage Sinks

This document describes the reliability features added to the mothership storage sink system for improved resilience in challenging network environments like SATCOM.

## Features

### 1. Per-Sink Retries with Jittered Exponential Backoff

- Configurable retry attempts with exponential backoff and jitter
- Retries on transient errors (timeouts, 5xx HTTP responses)
- No retry on permanent errors (4xx except 429)
- Honors `Retry-After` header when present

**Configuration:**
```bash
SINK_DEFAULT_MAX_RETRIES=5
SINK_DEFAULT_INITIAL_BACKOFF_MS=500
SINK_DEFAULT_MAX_BACKOFF_MS=30000
SINK_DEFAULT_JITTER_FACTOR=0.2
SINK_DEFAULT_TIMEOUT_MS=5000
```

### 2. Circuit Breakers

- Per-sink circuit breakers with three states: closed, open, half-open
- Automatically opens after consecutive failures
- Transitions to half-open after timeout
- Limits concurrent requests in half-open state

**Configuration:**
```bash
SINK_DEFAULT_FAILURE_THRESHOLD=5
SINK_DEFAULT_OPEN_DURATION_SEC=60
SINK_DEFAULT_HALF_OPEN_MAX_INFLIGHT=3
```

### 3. Persistent Queue (Store-and-Forward)

- Optional on-disk queue for events that fail to send
- Background processor retries queued events
- Dead Letter Queue (DLQ) for poison messages
- Bandwidth-limited flushing

**Configuration:**
```bash
QUEUE_ENABLED=true
QUEUE_DIR=./data/queue
QUEUE_MAX_BYTES=1073741824
QUEUE_FLUSH_INTERVAL_MS=2000
DLQ_DIR=./data/dlq
FLUSH_BANDWIDTH_BYTES_PER_SEC=1048576
```

### 4. Idempotency

- Prevents duplicate processing of identical event batches
- Configurable deduplication window
- Based on content hash of events

**Configuration:**
```bash
IDEMPOTENCY_WINDOW_SEC=86400
```

## SATCOM-Optimized Settings

For satellite/at-sea networks, use these recommended settings:

```bash
# Aggressive retries for flaky connections
SINK_DEFAULT_MAX_RETRIES=7
SINK_DEFAULT_INITIAL_BACKOFF_MS=1000
SINK_DEFAULT_MAX_BACKOFF_MS=60000
SINK_DEFAULT_JITTER_FACTOR=0.3

# Conservative circuit breaker
SINK_DEFAULT_FAILURE_THRESHOLD=5
SINK_DEFAULT_OPEN_DURATION_SEC=120
SINK_DEFAULT_HALF_OPEN_MAX_INFLIGHT=2

# Large persistent queue
QUEUE_MAX_BYTES=5368709120  # 5 GiB
FLUSH_BANDWIDTH_BYTES_PER_SEC=524288  # 0.5 MiB/s
```

## New Metrics

The following Prometheus metrics are available:

- `mship_sink_retry_total{sink}` - Total retries per sink
- `mship_sink_error_total{sink}` - Total errors per sink  
- `mship_sink_timeout_total{sink}` - Total timeouts per sink
- `mship_sink_circuit_state{sink}` - Circuit breaker state (0=closed, 1=open, 2=half-open)
- `mship_sink_circuit_open_total{sink}` - Total circuit breaker openings per sink
- `mship_queue_depth` - Current persistent queue depth
- `mship_queue_bytes` - Current persistent queue size in bytes

## Testing

Run the reliability tests:

```bash
cd mothership
python -m pytest tests/test_reliability.py tests/test_sinks_integration.py -v
```

Run the demo script:

```bash
cd mothership  
python test_reliability_demo.py
```

## Architecture

The reliability features are implemented as:

1. `SinkRetryManager` - Handles retry logic and backoff calculation
2. `SinkCircuitBreaker` - Implements circuit breaker pattern
3. `PersistentQueue` - Manages on-disk event queue and DLQ
4. `IdempotencyManager` - Tracks event batches to prevent duplicates
5. `ReliableSinkWrapper` - Integrates all features around existing sinks

These components are transparently integrated into the existing `SinksManager` without changing the `StorageSink` protocol.