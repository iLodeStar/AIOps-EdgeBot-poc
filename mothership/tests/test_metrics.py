"""Tests for metrics module."""

import pytest
from mothership.app.metrics import (
    get_metrics_content,
    mship_ingest_batches_total,
    mship_ingest_events_total,
    mship_written_events_total,
    mship_sink_written_total,
    mship_ingest_seconds,
    mship_pipeline_seconds,
    mship_sink_write_seconds,
    mship_requests_total,
    mship_active_connections,
    mship_loki_queue_size,
    METRICS_REGISTRY,
)


class TestMetrics:
    """Test metrics functionality."""

    def test_counter_metrics(self):
        """Test that counter metrics can be incremented."""
        initial_batches = mship_ingest_batches_total._value._value
        initial_events = mship_ingest_events_total._value._value
        initial_written = mship_written_events_total._value._value

        # Test batch counter
        mship_ingest_batches_total.inc()
        assert mship_ingest_batches_total._value._value == initial_batches + 1

        # Test events counter
        mship_ingest_events_total.inc(5)
        assert mship_ingest_events_total._value._value == initial_events + 5

        # Test written events counter
        mship_written_events_total.inc(10)
        assert mship_written_events_total._value._value == initial_written + 10

    def test_per_sink_metrics(self):
        """Test that per-sink metrics work correctly."""
        # Test sink written counter with labels
        mship_sink_written_total.labels(sink="loki").inc(3)
        mship_sink_written_total.labels(sink="tsdb").inc(7)

        # Test request counter with labels
        mship_requests_total.labels(
            method="POST", endpoint="/ingest", status="200"
        ).inc()
        mship_requests_total.labels(
            method="GET", endpoint="/metrics", status="200"
        ).inc()

        # Verify metrics are recorded
        metrics_content = get_metrics_content()
        assert 'mship_sink_written_total{sink="loki"}' in metrics_content
        assert 'mship_sink_written_total{sink="tsdb"}' in metrics_content
        assert (
            'mship_requests_total{endpoint="/ingest",method="POST",status="200"}'
            in metrics_content
        )

    def test_histogram_metrics(self):
        """Test that histogram metrics work correctly."""
        initial_ingest_count = 0
        initial_pipeline_count = 0
        initial_sink_count = 0

        # Get initial counts if they exist
        content_before = get_metrics_content()
        if "mship_ingest_seconds_count" in content_before:
            # Extract the count (this is simplified, in reality we'd parse properly)
            lines = content_before.split("\n")
            for line in lines:
                if "mship_ingest_seconds_count" in line and not line.startswith("#"):
                    initial_ingest_count = float(line.split()[-1])
                    break

        # Test timing with context manager
        with mship_ingest_seconds.time():
            pass  # Simulate work

        with mship_pipeline_seconds.time():
            pass  # Simulate work

        with mship_sink_write_seconds.labels(sink="loki").time():
            pass  # Simulate work

        # Check that histograms have recorded observations
        metrics_content = get_metrics_content()
        assert "mship_ingest_seconds_count" in metrics_content
        assert "mship_pipeline_seconds_count" in metrics_content
        assert 'mship_sink_write_seconds_count{sink="loki"}' in metrics_content

    def test_gauge_metrics(self):
        """Test that gauge metrics work correctly."""
        # Test active connections gauge
        mship_active_connections.set(5)
        assert mship_active_connections._value._value == 5

        # Test Loki queue size gauge
        mship_loki_queue_size.set(25)
        assert mship_loki_queue_size._value._value == 25

        # Verify in metrics output
        metrics_content = get_metrics_content()
        assert "mship_active_connections 5.0" in metrics_content
        assert "mship_loki_queue_size 25.0" in metrics_content

    def test_metrics_content_generation(self):
        """Test that metrics content can be generated."""
        initial_events = mship_ingest_events_total._value._value
        initial_connections = mship_active_connections._value._value

        # Add some sample metrics
        mship_ingest_events_total.inc(100)
        mship_active_connections.set(3)

        content = get_metrics_content()

        # Check basic structure
        assert isinstance(content, str)
        assert "mship_ingest_events_total" in content
        assert "mship_active_connections" in content
        assert str(float(initial_events + 100)) in content  # events count
        assert "3.0" in content  # active connections

    def test_custom_registry_isolation(self):
        """Test that custom registry is isolated from default registry."""
        from prometheus_client import REGISTRY, Counter

        # Create a counter in default registry
        default_counter = Counter(
            "test_default_counter", "Test counter in default registry"
        )
        default_counter.inc()

        # Our metrics should not appear in default registry
        from prometheus_client import generate_latest

        default_content = generate_latest(REGISTRY).decode("utf-8")
        assert "mship_ingest_events_total" not in default_content

        # But should appear in our custom registry
        our_content = get_metrics_content()
        assert "mship_ingest_events_total" in our_content
        assert "test_default_counter" not in our_content


class TestMetricsRequirements:
    """Test that all required metrics from the spec are present."""

    def test_required_counters_exist(self):
        """Test that all required counters from the spec exist."""
        required_counters = [
            "mship_ingest_batches_total",
            "mship_ingest_events_total",
            "mship_written_events_total",
            "mship_sink_written_total",
        ]

        content = get_metrics_content()
        for counter_name in required_counters:
            assert (
                counter_name in content
            ), f"Required counter {counter_name} not found in metrics"

    def test_required_histograms_exist(self):
        """Test that all required histograms from the spec exist."""
        required_histograms = [
            "mship_ingest_seconds",
            "mship_pipeline_seconds",
            "mship_sink_write_seconds",
        ]

        content = get_metrics_content()
        for histogram_name in required_histograms:
            assert (
                histogram_name in content
            ), f"Required histogram {histogram_name} not found in metrics"

    def test_per_sink_labels_work(self):
        """Test that per-sink labels work as required."""
        # Test sink-specific metrics
        mship_sink_written_total.labels(sink="loki").inc(5)
        mship_sink_written_total.labels(sink="timescaledb").inc(10)

        with mship_sink_write_seconds.labels(sink="loki").time():
            pass
        with mship_sink_write_seconds.labels(sink="timescaledb").time():
            pass

        content = get_metrics_content()

        # Verify sink labels are present
        assert 'sink="loki"' in content
        assert 'sink="timescaledb"' in content

        # Verify both counters and histograms have sink labels
        assert 'mship_sink_written_total{sink="loki"}' in content
        assert 'mship_sink_written_total{sink="timescaledb"}' in content
        assert 'mship_sink_write_seconds_count{sink="loki"}' in content
        assert 'mship_sink_write_seconds_count{sink="timescaledb"}' in content


class TestReliabilityMetrics:
    """Test reliability metrics functionality."""

    def test_reliability_metrics_exist(self):
        """Test that all reliability metrics are available."""
        from mothership.app.metrics import (
            mship_sink_retry_total,
            mship_sink_error_total,
            mship_sink_timeout_total,
            mship_sink_circuit_state,
            mship_sink_circuit_open_total,
            mship_queue_depth,
            mship_queue_bytes,
        )

        # Test that metrics can be used
        mship_sink_retry_total.labels(sink="test").inc()
        mship_sink_error_total.labels(sink="test").inc()
        mship_sink_timeout_total.labels(sink="test").inc()
        mship_sink_circuit_state.labels(sink="test").set(1)
        mship_sink_circuit_open_total.labels(sink="test").inc()
        mship_queue_depth.set(10)
        mship_queue_bytes.set(1024)

        from mothership.app.metrics import get_metrics_content

        content = get_metrics_content()

        # Verify metrics are present
        assert "mship_sink_retry_total" in content
        assert "mship_sink_error_total" in content
        assert "mship_sink_timeout_total" in content
        assert "mship_sink_circuit_state" in content
        assert "mship_sink_circuit_open_total" in content
        assert "mship_queue_depth" in content
        assert "mship_queue_bytes" in content
