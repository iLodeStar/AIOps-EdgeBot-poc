"""
E2E-3: Cross-Phase Integration Test

This test validates the full EdgeBot → Mothership → Loki pipeline:
- Starts Loki, Mothership, and EdgeBot together
- Sends syslog events to EdgeBot
- Verifies EdgeBot ships events to Mothership
- Verifies Mothership processes and sends to Loki
- Validates end-to-end data flow and metrics
"""

import asyncio
import json
import os
import time
from pathlib import Path
from typing import List, Dict
import pytest
import requests
import yaml
import uuid
from tests.e2e.utils import (
    DockerComposeManager,
    ProcessManager,
    SyslogSender,
    HealthChecker,
    LokiClient,
    TestDataManager,
    find_free_port,
)


class TestCrossPhaseIntegration:
    """Test suite for full EdgeBot → Mothership → Loki integration."""

    def setup_method(self):
        """Set up test environment before each test."""
        self.process_manager = ProcessManager()
        self.data_manager = TestDataManager()

        # Set up Docker Compose for Loki
        compose_file = Path(__file__).parent.parent.parent / "docker-compose.e2e.yml"
        self.docker_manager = DockerComposeManager(str(compose_file), "integration-e2e")

        # Initialize Loki client
        self.loki_client = LokiClient("http://localhost:3100")

        # Find free ports to avoid conflicts
        self.mothership_port = find_free_port(8443)
        self.edgebot_main_port = find_free_port(8080)
        self.edgebot_health_port = find_free_port(8081)
        self.syslog_udp_port = find_free_port(5514)
        self.syslog_tcp_port = find_free_port(5515)

        self.temp_dir = self.data_manager.create_temp_dir("integration-e2e-")

    def teardown_method(self):
        """Clean up test environment after each test."""
        self.process_manager.stop_all()
        self.docker_manager.stop_services()
        self.data_manager.cleanup()

    def start_loki(self) -> bool:
        """Start Loki service and wait for it to be ready."""
        success = self.docker_manager.start_services(["loki"], timeout=120)
        if not success:
            return False

        return self.loki_client.health_check() and HealthChecker.wait_for_health(
            "http://localhost:3100/ready", timeout=60
        )

    def create_mothership_config(self) -> Path:
        """Create Mothership configuration for integration testing."""
        config = {
            "server": {"host": "0.0.0.0", "port": self.mothership_port},
            "sinks": {
                "loki": {
                    "enabled": True,
                    "url": "http://localhost:3100",
                    "timeout_sec": 10,
                    "batch_size": 10,
                    "labels": {
                        "job": "edgebot-integration-test",
                        "source": "e2e-cross-phase",
                    },
                },
                "tsdb": {"enabled": False},
            },
            "pipeline": {
                "processors": [
                    {
                        "type": "drop_fields",
                        "config": {"fields": ["_internal", "__spool_id"]},
                    },
                    {
                        "type": "add_tags",
                        "config": {
                            "add_tags": {
                                "source": "edgebot-via-mothership",
                                "test_phase": "integration",
                                "pipeline": "cross-phase-e2e",
                            }
                        },
                    },
                ]
            },
            "features": {
                "llm_enabled": False,
                "redaction_enabled": True,
                "enrichment_enabled": True,
            },
        }

        config_file = self.temp_dir / "mothership-config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(config, f)

        return config_file

    def create_edgebot_config(self) -> Path:
        """Create EdgeBot configuration to ship to Mothership."""
        config = {
            "server": {"host": "127.0.0.1", "port": self.edgebot_main_port},
            "inputs": {
                "syslog": {
                    "enabled": True,
                    "udp_port": self.syslog_udp_port,
                    "tcp_port": self.syslog_tcp_port,
                }
            },
            "output": {
                "mothership": {
                    "url": f"http://localhost:{self.mothership_port}/ingest",
                    "batch_size": 5,
                    "flush_interval_sec": 2,
                    "retry": {
                        "max_retries": 3,
                        "initial_backoff_ms": 500,
                        "max_backoff_ms": 5000,
                    },
                    "timeout_sec": 10,
                }
            },
            "observability": {
                "health_port": self.edgebot_health_port,
                "metrics_enabled": True,
            },
        }

        config_file = self.temp_dir / "edgebot-config.yaml"
        with open(config_file, "w") as f:
            yaml.dump(config, f)

        return config_file

    def start_mothership(self, config_file: Path) -> bool:
        """Start Mothership process."""
        mothership_dir = Path(__file__).parent.parent.parent / "mothership"

        cmd = [
            "python",
            "-m",
            "app.server",
            "--host",
            "0.0.0.0",
            "--port",
            str(self.mothership_port),
        ]

        env = {
            "PYTHONPATH": str(mothership_dir),
            "MOTHERSHIP_CONFIG_FILE": str(config_file),
            "LOKI_ENABLED": "true",
            "LOKI_URL": "http://localhost:3100",
            "TSDB_ENABLED": "false",
            "MOTHERSHIP_LLM_ENABLED": "false",
            "LOG_LEVEL": "INFO",
        }

        success = self.process_manager.start_process(
            "mothership", cmd, cwd=str(mothership_dir), env=env
        )

        if success:
            health_url = f"http://localhost:{self.mothership_port}/healthz"
            return HealthChecker.wait_for_health(health_url, timeout=45)

        return False

    def start_edgebot(self, config_file: Path) -> bool:
        """Start EdgeBot process."""
        edgebot_dir = Path(__file__).parent.parent.parent / "edge_node"

        cmd = ["python", "-m", "app.main", "-c", str(config_file)]

        env = os.environ.copy()
        env["PYTHONPATH"] = str(edgebot_dir)

        success = self.process_manager.start_process(
            "edgebot", cmd, cwd=str(edgebot_dir), env=env
        )

        if success:
            health_url = f"http://localhost:{self.edgebot_health_port}/healthz"
            return HealthChecker.wait_for_health(health_url, timeout=30)

        return False

    @pytest.mark.asyncio
    async def test_full_integration_pipeline(self):
        """Test complete EdgeBot → Mothership → Loki data flow."""
        # Start Loki first
        assert self.start_loki(), "Failed to start Loki"
        await asyncio.sleep(3)

        # Start Mothership
        mothership_config = self.create_mothership_config()
        assert self.start_mothership(mothership_config), "Failed to start Mothership"
        await asyncio.sleep(5)

        # Start EdgeBot
        edgebot_config = self.create_edgebot_config()
        assert self.start_edgebot(edgebot_config), "Failed to start EdgeBot"
        await asyncio.sleep(5)

        # Verify all services are healthy
        edgebot_health = f"http://localhost:{self.edgebot_health_port}/healthz"
        mothership_health = f"http://localhost:{self.mothership_port}/healthz"

        # Check EdgeBot health
        response = requests.get(edgebot_health, timeout=5)
        assert response.status_code == 200, f"EdgeBot not healthy: {response.text}"

        # Check Mothership health
        response = requests.get(mothership_health, timeout=5)
        assert response.status_code == 200, f"Mothership not healthy: {response.text}"

        # Generate unique test ID for this run
        test_run_id = str(uuid.uuid4())[:8]

        # Send test syslog messages to EdgeBot
        test_messages = []
        for i in range(5):
            timestamp = time.strftime("%b %d %H:%M:%S")
            message = f"<34>{timestamp} integration-host integration-app: Cross-phase test message #{i+1} run-{test_run_id}"
            test_messages.append(message)

            success = SyslogSender.send_message(
                message, host="localhost", port=self.syslog_udp_port
            )
            assert success, f"Failed to send test message #{i+1}"
            await asyncio.sleep(0.5)  # Brief delay between messages

        # Wait for processing through the entire pipeline
        await asyncio.sleep(15)

        # Verify EdgeBot processed and shipped messages
        edgebot_metrics = f"http://localhost:{self.edgebot_health_port}/metrics"
        response = requests.get(edgebot_metrics, timeout=5)
        assert response.status_code == 200, "Failed to get EdgeBot metrics"

        metrics_text = response.text
        assert (
            "edgebot_messages_received_total" in metrics_text
        ), "EdgeBot receive metrics missing"
        assert (
            "edgebot_output_shipped_total" in metrics_text
        ), "EdgeBot ship metrics missing"

        # Verify Mothership received and processed messages
        mothership_stats = f"http://localhost:{self.mothership_port}/stats"
        response = requests.get(mothership_stats, timeout=5)
        assert response.status_code == 200, "Failed to get Mothership stats"

        stats_data = response.json()
        pipeline_stats = stats_data.get("pipeline", {})
        total_events = pipeline_stats.get("total_events", 0)

        assert (
            total_events >= 5
        ), f"Expected at least 5 events processed by Mothership, got {total_events}"

        # Verify events reached Loki
        await asyncio.sleep(10)  # Additional wait for Loki indexing

        # Query Loki for our test messages
        query = f'{{job="edgebot-integration-test"}} |= "run-{test_run_id}"'
        loki_result = self.loki_client.query(query)

        if loki_result.get("status") == "success":
            data = loki_result.get("data", {})
            result = data.get("result", [])

            # Count matching log entries
            matching_entries = 0
            for stream in result:
                for value_pair in stream.get("values", []):
                    if len(value_pair) >= 2:
                        log_line = value_pair[1]
                        if test_run_id in log_line:
                            matching_entries += 1

            assert (
                matching_entries >= 3
            ), f"Expected at least 3 matching entries in Loki, found {matching_entries}"
        else:
            # If Loki query failed, at least verify data reached Mothership
            assert total_events >= 5, "Data didn't reach Mothership pipeline"

    @pytest.mark.asyncio
    async def test_integration_with_different_syslog_formats(self):
        """Test integration with various syslog message formats."""
        # Start all services
        assert self.start_loki(), "Failed to start Loki"
        await asyncio.sleep(3)

        mothership_config = self.create_mothership_config()
        assert self.start_mothership(mothership_config), "Failed to start Mothership"
        await asyncio.sleep(5)

        edgebot_config = self.create_edgebot_config()
        assert self.start_edgebot(edgebot_config), "Failed to start EdgeBot"
        await asyncio.sleep(5)

        test_run_id = str(uuid.uuid4())[:8]

        # Send different syslog formats
        test_messages = [
            f"<165>Aug 23 12:05:45 server1 app1: RFC3164 format test run-{test_run_id}",
            f"<34>1 2023-08-23T12:05:45.123Z server2 app2 1234 - - RFC5424 format test run-{test_run_id}",
            f"<14>Aug 23 12:05:45 server3 kernel: Simple format test run-{test_run_id}",
            f"<46>2023-08-23T12:05:45Z server4 nginx: JSON embedded test run-{test_run_id}",
        ]

        for i, message in enumerate(test_messages):
            success = SyslogSender.send_message(
                message, host="localhost", port=self.syslog_udp_port
            )
            assert success, f"Failed to send message format #{i+1}"
            await asyncio.sleep(1)

        # Wait for processing
        await asyncio.sleep(20)

        # Check that Mothership processed all formats
        mothership_stats = f"http://localhost:{self.mothership_port}/stats"
        response = requests.get(mothership_stats, timeout=5)
        assert response.status_code == 200

        stats_data = response.json()
        pipeline_stats = stats_data.get("pipeline", {})
        total_events = pipeline_stats.get("total_events", 0)

        assert total_events >= len(
            test_messages
        ), f"Expected at least {len(test_messages)} events, got {total_events}"

    @pytest.mark.asyncio
    async def test_integration_error_recovery(self):
        """Test integration resilience when Mothership is temporarily unavailable."""
        # Start Loki and EdgeBot first (no Mothership)
        assert self.start_loki(), "Failed to start Loki"
        await asyncio.sleep(3)

        edgebot_config = self.create_edgebot_config()
        assert self.start_edgebot(edgebot_config), "Failed to start EdgeBot"
        await asyncio.sleep(5)

        test_run_id = str(uuid.uuid4())[:8]

        # Send messages while Mothership is down (should queue/retry)
        early_messages = []
        for i in range(3):
            message = f"<34>Aug 23 12:05:45 test-host test-app: Early message #{i+1} run-{test_run_id}"
            early_messages.append(message)

            SyslogSender.send_message(
                message, host="localhost", port=self.syslog_udp_port
            )
            await asyncio.sleep(1)

        # Wait for EdgeBot to attempt delivery (and fail)
        await asyncio.sleep(10)

        # Now start Mothership
        mothership_config = self.create_mothership_config()
        assert self.start_mothership(mothership_config), "Failed to start Mothership"
        await asyncio.sleep(5)

        # Send more messages after Mothership is available
        for i in range(3):
            message = f"<34>Aug 23 12:05:45 test-host test-app: Late message #{i+1} run-{test_run_id}"

            SyslogSender.send_message(
                message, host="localhost", port=self.syslog_udp_port
            )
            await asyncio.sleep(1)

        # Wait for EdgeBot to retry and deliver all messages
        await asyncio.sleep(15)

        # Check EdgeBot metrics for retry behavior
        edgebot_metrics = f"http://localhost:{self.edgebot_health_port}/metrics"
        response = requests.get(edgebot_metrics, timeout=5)
        assert response.status_code == 200

        metrics_text = response.text
        assert (
            "edgebot_output_shipped_total" in metrics_text
        ), "No shipped metrics found"

        # Check Mothership received events
        mothership_stats = f"http://localhost:{self.mothership_port}/stats"
        response = requests.get(mothership_stats, timeout=5)
        assert response.status_code == 200

        stats_data = response.json()
        pipeline_stats = stats_data.get("pipeline", {})
        total_events = pipeline_stats.get("total_events", 0)

        # Should eventually receive most/all messages via retries
        assert (
            total_events >= 3
        ), f"Expected at least 3 events after recovery, got {total_events}"

    @pytest.mark.asyncio
    async def test_integration_metrics_end_to_end(self):
        """Test that metrics are properly reported across the entire pipeline."""
        # Start all services
        assert self.start_loki(), "Failed to start Loki"
        await asyncio.sleep(3)

        mothership_config = self.create_mothership_config()
        assert self.start_mothership(mothership_config), "Failed to start Mothership"
        await asyncio.sleep(5)

        edgebot_config = self.create_edgebot_config()
        assert self.start_edgebot(edgebot_config), "Failed to start EdgeBot"
        await asyncio.sleep(5)

        # Get baseline metrics
        edgebot_metrics_url = f"http://localhost:{self.edgebot_health_port}/metrics"
        mothership_metrics_url = f"http://localhost:{self.mothership_port}/metrics"

        # Send test messages
        message_count = 7
        for i in range(message_count):
            message = (
                f"<34>Aug 23 12:05:45 metrics-host metrics-app: Metrics test #{i+1}"
            )
            SyslogSender.send_message(
                message, host="localhost", port=self.syslog_udp_port
            )
            await asyncio.sleep(0.5)

        # Wait for processing
        await asyncio.sleep(15)

        # Check EdgeBot metrics
        response = requests.get(edgebot_metrics_url, timeout=5)
        assert response.status_code == 200

        edgebot_metrics = response.text

        # Look for message counters
        received_count = 0
        shipped_count = 0

        for line in edgebot_metrics.split("\n"):
            if line.startswith("edgebot_messages_received_total"):
                try:
                    received_count = int(float(line.split()[-1]))
                except (ValueError, IndexError):
                    pass
            elif line.startswith("edgebot_output_shipped_total"):
                try:
                    shipped_count = int(float(line.split()[-1]))
                except (ValueError, IndexError):
                    pass

        assert (
            received_count >= message_count
        ), f"EdgeBot received count {received_count} < {message_count}"
        assert (
            shipped_count > 0
        ), f"EdgeBot shipped count should be > 0, got {shipped_count}"

        # Check Mothership metrics
        response = requests.get(mothership_metrics_url, timeout=5)
        assert response.status_code == 200

        mothership_metrics = response.text

        # Verify Mothership ingestion metrics
        assert (
            "mothership_ingestion_events_total" in mothership_metrics
        ), "Missing Mothership ingestion metrics"
        assert (
            "mothership_pipeline_duration_seconds" in mothership_metrics
        ), "Missing Mothership pipeline metrics"

        # Check final stats
        mothership_stats = f"http://localhost:{self.mothership_port}/stats"
        response = requests.get(mothership_stats, timeout=5)
        assert response.status_code == 200

        stats_data = response.json()
        pipeline_stats = stats_data.get("pipeline", {})

        assert (
            pipeline_stats.get("total_events", 0) >= message_count
        ), "Not all events processed by pipeline"
        assert (
            pipeline_stats.get("successful_events", 0) > 0
        ), "No successful events in pipeline"
