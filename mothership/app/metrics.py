"""Prometheus metrics for Mothership observability.

This module provides a centralized metrics registry and all the counters, 
histograms, and gauges needed for observability as specified in the requirements.
"""

from prometheus_client import Counter, Histogram, Gauge, CollectorRegistry, generate_latest

# Use a custom registry to avoid conflicts with default registry
# This ensures clean metrics for testing and prevents duplicate collectors
METRICS_REGISTRY = CollectorRegistry()

# Counters as specified in requirements
mship_ingest_batches_total = Counter(
    'mship_ingest_batches_total',
    'Total number of ingestion batches processed',
    registry=METRICS_REGISTRY
)

mship_ingest_events_total = Counter(
    'mship_ingest_events_total', 
    'Total number of events ingested',
    registry=METRICS_REGISTRY
)

mship_written_events_total = Counter(
    'mship_written_events_total',
    'Total number of events written to all sinks', 
    registry=METRICS_REGISTRY
)

mship_sink_written_total = Counter(
    'mship_sink_written_total',
    'Total number of events written per sink',
    ['sink'],
    registry=METRICS_REGISTRY
)

# Histograms as specified in requirements
mship_ingest_seconds = Histogram(
    'mship_ingest_seconds',
    'Time spent processing ingest requests',
    registry=METRICS_REGISTRY
)

mship_pipeline_seconds = Histogram(
    'mship_pipeline_seconds',
    'Time spent in processing pipeline',
    registry=METRICS_REGISTRY
)

mship_sink_write_seconds = Histogram(
    'mship_sink_write_seconds',
    'Time spent writing to each sink',
    ['sink'],
    registry=METRICS_REGISTRY
)

# Additional metrics that may be useful (from existing server.py)
mship_requests_total = Counter(
    'mship_requests_total',
    'Total HTTP requests processed',
    ['method', 'endpoint', 'status'],
    registry=METRICS_REGISTRY
)

mship_active_connections = Gauge(
    'mship_active_connections',
    'Number of active database connections',
    registry=METRICS_REGISTRY
)

# Loki-specific metrics (queue size for monitoring batching)
mship_loki_queue_size = Gauge(
    'mship_loki_queue_size',
    'Current size of Loki batching queue',
    registry=METRICS_REGISTRY
)

# Per-sink retry metrics
mship_sink_retry_total = Counter(
    'mship_sink_retry_total',
    'Total number of retry attempts per sink',
    ['sink'],
    registry=METRICS_REGISTRY
)

mship_sink_error_total = Counter(
    'mship_sink_error_total',
    'Total number of errors per sink',
    ['sink'],
    registry=METRICS_REGISTRY
)

mship_sink_timeout_total = Counter(
    'mship_sink_timeout_total',
    'Total number of timeouts per sink',
    ['sink'],
    registry=METRICS_REGISTRY
)

# Per-sink circuit breaker metrics  
mship_sink_circuit_state = Gauge(
    'mship_sink_circuit_state',
    'Circuit breaker state per sink (0=closed, 1=open, 2=half-open)',
    ['sink'],
    registry=METRICS_REGISTRY
)

mship_sink_circuit_open_total = Counter(
    'mship_sink_circuit_open_total',
    'Total number of times circuit breaker opened per sink',
    ['sink'],
    registry=METRICS_REGISTRY
)

# Store-and-forward queue metrics
mship_sink_queue_size = Gauge(
    'mship_sink_queue_size',
    'Current number of events in persistent queue per sink',
    ['sink'],
    registry=METRICS_REGISTRY
)

mship_sink_queue_bytes = Gauge(
    'mship_sink_queue_bytes',
    'Current size of persistent queue in bytes per sink',
    ['sink'],
    registry=METRICS_REGISTRY
)

mship_sink_dlq_total = Counter(
    'mship_sink_dlq_total',
    'Total number of events sent to dead letter queue per sink',
    ['sink'],
    registry=METRICS_REGISTRY
)


def get_metrics_content() -> str:
    """Generate Prometheus metrics content from custom registry."""
    return generate_latest(METRICS_REGISTRY).decode('utf-8')


def reset_metrics():
    """Reset all metrics - useful for testing."""
    # Note: We can't actually reset prometheus metrics once created.
    # This function exists for API compatibility but doesn't do a full reset.
    # In practice, for testing, we should use a separate test registry or 
    # accept that metrics accumulate across tests.
    pass