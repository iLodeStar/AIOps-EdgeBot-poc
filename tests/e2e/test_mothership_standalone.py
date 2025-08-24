"""
E2E-2: Mothership Standalone Test

This test validates Mothership functionality with Loki sink:
- Starts Loki via docker compose
- Starts Mothership with LOKI_ENABLED=true, TSDB_ENABLED=false
- POSTs test events to /ingest endpoint
- Validates response success and processing metrics
- Optionally verifies Loki received logs via API query
"""

import asyncio
import json
import time
from pathlib import Path
from typing import List, Dict
import pytest
import requests
import yaml
from tests.e2e.utils import (
    DockerComposeManager,
    ProcessManager,
    HealthChecker,
    LokiClient,
    TestDataManager,
    find_free_port,
)


class TestMothershipStandalone:
    """Test suite for Mothership standalone functionality."""

    def setup_method(self):
        """Set up test environment before each test."""
        self.process_manager = ProcessManager()
        self.data_manager = TestDataManager()

        # Set up Docker Compose for Loki
        compose_file = Path(__file__).parent.parent.parent / "docker-compose.e2e.yml"
        self.docker_manager = DockerComposeManager(str(compose_file), "mothership-e2e")

        # Initialize Loki client
        self.loki_client = LokiClient("http://localhost:3100")

        # Find free ports
        self.mothership_port = find_free_port(8443)

        self.temp_dir = self.data_manager.create_temp_dir("mothership-standalone-")

    def teardown_method(self):
        """Clean up test environment after each test."""
        self.process_manager.stop_all()
        self.docker_manager.stop_services()
        self.data_manager.cleanup()

    def start_loki(self) -> bool:
        """Start Loki service and wait for it to be ready."""
        # Start Loki service
        success = self.docker_manager.start_services(["loki"], timeout=120)
        if not success:
            return False

        # Wait for Loki to be ready
        return self.loki_client.health_check() and HealthChecker.wait_for_health(
            "http://localhost:3100/ready", timeout=60
        )

    def create_mothership_config(self) -> Path:
        """Create Mothership configuration for Loki-only sink."""
        config = {
            "server": {"host": "0.0.0.0", "port": self.mothership_port},
            "sinks": {
                "loki": {
                    "enabled": True,
                    "url": "http://localhost:3100",
                    "timeout_sec": 10,
                    "batch_size": 100,
                },
                "tsdb": {"enabled": False},
            },
            "pipeline": {
                "processors": [
                    {
                        "type": "drop_fields",
                        "config": {"fields": ["_internal", "__temp"]},
                    },
                    {
                        "type": "add_tags",
                        "config": {
                            "add_tags": {
                                "source": "e2e-mothership-test",
                                "test_run": "standalone",
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

    def start_mothership(self, config_file: Path) -> bool:
        """Start Mothership process with given configuration."""
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
            # Wait for Mothership to be ready
            health_url = f"http://localhost:{self.mothership_port}/healthz"
            return HealthChecker.wait_for_health(health_url, timeout=45)

        return False

    def create_test_events(self, count: int = 5) -> List[Dict]:
        """Create test events for ingestion."""
        events = []
        for i in range(count):
            event = {
                "timestamp": "2023-08-23T12:05:45.000Z",
                "message": f"Test event #{i+1} from Mothership E2E test",
                "hostname": "test-host",
                "service": "test-service",
                "severity": "info",
                "facility": "local0",
                "tags": {"test_id": f"mothership-test-{i+1}", "category": "e2e-test"},
                "raw_message": f"<14>Aug 23 12:05:45 test-host test-service: Test event #{i+1}",
            }
            events.append(event)

        return events

    @pytest.mark.asyncio
    async def test_mothership_basic_ingestion(self):
        """Test basic Mothership ingestion functionality with Loki sink."""
        # Start Loki first
        assert self.start_loki(), "Failed to start Loki"
        await asyncio.sleep(2)

        # Create Mothership configuration
        config_file = self.create_mothership_config()

        # Start Mothership
        assert self.start_mothership(config_file), "Failed to start Mothership"
        await asyncio.sleep(5)

        # Test health endpoint first
        health_url = f"http://localhost:{self.mothership_port}/healthz"
        response = requests.get(health_url, timeout=10)
        assert response.status_code == 200, f"Health check failed: {response.text}"

        health_data = response.json()
        assert (
            health_data.get("status") == "healthy"
        ), f"Mothership not healthy: {health_data}"

        # Verify Loki sink is enabled
        sinks = health_data.get("sinks", {})
        loki_sink = sinks.get("loki", {})
        assert loki_sink.get("enabled") == True, f"Loki sink not enabled: {sinks}"
        assert loki_sink.get("healthy") == True, f"Loki sink not healthy: {sinks}"

        # Create and send test events
        test_events = self.create_test_events(count=3)

        ingest_url = f"http://localhost:{self.mothership_port}/ingest"
        response = requests.post(
            ingest_url,
            json={"messages": test_events},
            headers={"Content-Type": "application/json"},
            timeout=15,
        )

        assert (
            response.status_code == 200
        ), f"Ingestion failed: {response.status_code} - {response.text}"

        response_data = response.json()
        assert (
            response_data.get("status") == "success"
        ), f"Ingestion not successful: {response_data}"
        assert (
            response_data.get("processed_events") == 3
        ), f"Unexpected event count: {response_data}"

        # Wait for processing
        await asyncio.sleep(3)

        # Check metrics endpoint
        metrics_url = f"http://localhost:{self.mothership_port}/metrics"
        response = requests.get(metrics_url, timeout=10)
        assert (
            response.status_code == 200
        ), f"Metrics endpoint failed: {response.status_code}"

        metrics_text = response.text

        # Check for expected metrics
        expected_metrics = [
            "mothership_ingestion_requests_total",
            "mothership_ingestion_events_total",
            "mothership_pipeline_duration_seconds",
        ]

        for metric in expected_metrics:
            assert metric in metrics_text, f"Expected metric '{metric}' not found"

    @pytest.mark.asyncio
    async def test_mothership_pipeline_processing(self):
        """Test Mothership pipeline processors are working correctly."""
        # Start infrastructure
        assert self.start_loki(), "Failed to start Loki"
        await asyncio.sleep(2)

        config_file = self.create_mothership_config()
        assert self.start_mothership(config_file), "Failed to start Mothership"
        await asyncio.sleep(5)

        # Create events with fields that should be dropped/modified
        test_events = [
            {
                "timestamp": "2023-08-23T12:05:45.000Z",
                "message": "Test pipeline processing",
                "hostname": "test-host",
                "_internal": "should_be_dropped",
                "__temp": "also_should_be_dropped",
                "keep_this": "should_remain",
                "raw_message": "<14>Aug 23 12:05:45 test-host app: Test pipeline",
            }
        ]

        # Send to Mothership
        ingest_url = f"http://localhost:{self.mothership_port}/ingest"
        response = requests.post(ingest_url, json={"messages": test_events}, timeout=15)

        assert response.status_code == 200, f"Ingestion failed: {response.text}"

        # Wait for processing
        await asyncio.sleep(5)

        # Check stats endpoint for pipeline details
        stats_url = f"http://localhost:{self.mothership_port}/stats"
        response = requests.get(stats_url, timeout=10)
        assert (
            response.status_code == 200
        ), f"Stats endpoint failed: {response.status_code}"

        stats_data = response.json()

        # Verify pipeline processing occurred
        pipeline_stats = stats_data.get("pipeline", {})
        assert (
            pipeline_stats.get("total_events", 0) > 0
        ), f"No events processed: {stats_data}"

        # Check processor stats
        processors = pipeline_stats.get("processors", {})
        assert (
            "DropFields" in processors
        ), f"DropFields processor not found: {processors}"
        assert "AddTags" in processors, f"AddTags processor not found: {processors}"

    @pytest.mark.asyncio
    async def test_mothership_loki_integration(self):
        """Test that events actually reach Loki and can be queried."""
        # Start infrastructure
        assert self.start_loki(), "Failed to start Loki"
        await asyncio.sleep(3)

        config_file = self.create_mothership_config()
        assert self.start_mothership(config_file), "Failed to start Mothership"
        await asyncio.sleep(5)

        # Create unique test events
        import uuid

        test_id = str(uuid.uuid4())[:8]

        test_events = [
            {
                "timestamp": "2023-08-23T12:05:45.000Z",
                "message": f"Unique test message for Loki query {test_id}",
                "hostname": "loki-test-host",
                "service": "loki-test-service",
                "severity": "info",
                "tags": {"test_id": test_id, "category": "loki-integration"},
            }
        ]

        # Send to Mothership
        ingest_url = f"http://localhost:{self.mothership_port}/ingest"
        response = requests.post(ingest_url, json={"messages": test_events}, timeout=15)

        assert response.status_code == 200, f"Ingestion failed: {response.text}"

        # Wait for Loki ingestion
        await asyncio.sleep(10)

        # Query Loki to verify the event was stored
        # Use a query that should match our test event
        query = f'{{test_id="{test_id}"}}'
        loki_result = self.loki_client.query(query)

        if loki_result.get("status") == "success":
            data = loki_result.get("data", {})
            result = data.get("result", [])

            # Should find at least one matching log entry
            assert len(result) > 0, f"No logs found in Loki for test_id {test_id}"

            # Check that our test message appears in the results
            found_message = False
            for stream in result:
                for value_pair in stream.get("values", []):
                    if len(value_pair) >= 2:
                        log_line = value_pair[1]  # Second element is the log message
                        if test_id in log_line:
                            found_message = True
                            break

            assert (
                found_message
            ), f"Test message with ID {test_id} not found in Loki results"
        else:
            # If Loki query failed, at least verify Mothership processed it
            stats_url = f"http://localhost:{self.mothership_port}/stats"
            response = requests.get(stats_url, timeout=10)
            assert response.status_code == 200

            stats_data = response.json()
            pipeline_stats = stats_data.get("pipeline", {})
            assert (
                pipeline_stats.get("total_events", 0) > 0
            ), "No events processed by pipeline"

    @pytest.mark.asyncio
    async def test_mothership_error_handling(self):
        """Test Mothership error handling with invalid events."""
        # Start infrastructure
        assert self.start_loki(), "Failed to start Loki"
        await asyncio.sleep(2)

        config_file = self.create_mothership_config()
        assert self.start_mothership(config_file), "Failed to start Mothership"
        await asyncio.sleep(5)

        # Test 1: Send malformed JSON
        ingest_url = f"http://localhost:{self.mothership_port}/ingest"

        response = requests.post(
            ingest_url,
            data="invalid json",
            headers={"Content-Type": "application/json"},
            timeout=10,
        )

        # Should return 400 for malformed JSON
        assert (
            response.status_code == 400
        ), f"Expected 400 for malformed JSON, got {response.status_code}"

        # Test 2: Send missing required fields
        invalid_events = [
            {
                # Missing timestamp and message
                "hostname": "test-host"
            }
        ]

        response = requests.post(
            ingest_url, json={"messages": invalid_events}, timeout=10
        )

        # Should either accept and handle gracefully, or return error
        # The exact behavior depends on implementation, but shouldn't crash
        assert response.status_code in [
            200,
            400,
        ], f"Unexpected response for invalid events: {response.status_code}"

        # Test 3: Verify service is still healthy after errors
        health_url = f"http://localhost:{self.mothership_port}/healthz"
        response = requests.get(health_url, timeout=10)
        assert (
            response.status_code == 200
        ), "Service became unhealthy after error handling"

    @pytest.mark.asyncio
    async def test_mothership_batch_processing(self):
        """Test Mothership handling of large batches of events."""
        # Start infrastructure
        assert self.start_loki(), "Failed to start Loki"
        await asyncio.sleep(2)

        config_file = self.create_mothership_config()
        assert self.start_mothership(config_file), "Failed to start Mothership"
        await asyncio.sleep(5)

        # Create a large batch of events
        batch_size = 50
        test_events = []
        for i in range(batch_size):
            event = {
                "timestamp": "2023-08-23T12:05:45.000Z",
                "message": f"Batch test event #{i+1}",
                "hostname": f"batch-host-{i % 5}",  # Vary hostnames
                "service": "batch-test-service",
                "severity": "info" if i % 2 == 0 else "warn",
                "tags": {"batch_index": str(i), "batch_test": "true"},
            }
            test_events.append(event)

        # Send large batch
        ingest_url = f"http://localhost:{self.mothership_port}/ingest"
        response = requests.post(
            ingest_url,
            json={"messages": test_events},
            timeout=30,  # Longer timeout for large batch
        )

        assert response.status_code == 200, f"Batch ingestion failed: {response.text}"

        response_data = response.json()
        assert (
            response_data.get("processed_events") == batch_size
        ), f"Not all events received: {response_data}"

        # Wait for processing
        await asyncio.sleep(10)

        # Check final stats
        stats_url = f"http://localhost:{self.mothership_port}/stats"
        response = requests.get(stats_url, timeout=10)
        assert response.status_code == 200

        stats_data = response.json()
        pipeline_stats = stats_data.get("pipeline", {})
        total_events = pipeline_stats.get("total_events", 0)

        assert (
            total_events >= batch_size
        ), f"Expected at least {batch_size} events processed, got {total_events}"
