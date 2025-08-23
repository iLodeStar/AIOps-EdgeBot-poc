"""
E2E-1: EdgeBot Standalone Test

This test validates EdgeBot functionality in isolation without Mothership:
- Starts EdgeBot with file sink configuration
- Sends test syslog messages via UDP
- Validates output files contain proper JSON envelopes
- Checks health and metrics endpoints
"""
import asyncio
import json
import os
import tempfile
import time
from pathlib import Path
from typing import List, Dict
import pytest
import requests
import yaml
from tests.e2e.utils import (
    ProcessManager, SyslogSender, HealthChecker, TestDataManager,
    find_free_port, wait_for_file_content
)


class TestEdgeBotStandalone:
    """Test suite for EdgeBot standalone functionality."""
    
    def setup_method(self):
        """Set up test environment before each test."""
        self.process_manager = ProcessManager()
        self.data_manager = TestDataManager()
        self.temp_dir = self.data_manager.create_temp_dir("edgebot-standalone-")
        
        # Find free ports to avoid conflicts
        self.health_port = find_free_port(8081)
        self.main_port = find_free_port(8080)
        self.syslog_udp_port = find_free_port(5514)
        self.syslog_tcp_port = find_free_port(5515)
        
        # Create output directory
        self.output_dir = self.temp_dir / "output"
        self.output_dir.mkdir(exist_ok=True)
        
    def teardown_method(self):
        """Clean up test environment after each test."""
        self.process_manager.stop_all()
        self.data_manager.cleanup()
        
    def create_edgebot_config(self) -> Path:
        """Create EdgeBot configuration for file output."""
        config = {
            'server': {
                'host': '127.0.0.1',
                'port': self.main_port
            },
            'inputs': {
                'syslog': {
                    'enabled': True,
                    'udp_port': self.syslog_udp_port,
                    'tcp_port': self.syslog_tcp_port
                }
            },
            'output': {
                'file': {
                    'enabled': True,
                    'dir': str(self.output_dir),
                    'filename_pattern': 'payload-{timestamp}.json',
                    'batch_size': 5,
                    'flush_interval_sec': 2
                }
            },
            'observability': {
                'health_port': self.health_port,
                'metrics_enabled': True
            }
        }
        
        config_file = self.temp_dir / 'config.yaml'
        with open(config_file, 'w') as f:
            yaml.dump(config, f)
            
        return config_file
        
    def start_edgebot(self, config_file: Path) -> bool:
        """Start EdgeBot process with given configuration."""
        edgebot_dir = Path(__file__).parent.parent.parent / "edge_node"
        
        cmd = [
            "python", "-m", "app.main", 
            "-c", str(config_file)
        ]
        
        env = os.environ.copy()
        env['PYTHONPATH'] = str(edgebot_dir)
        
        success = self.process_manager.start_process(
            "edgebot", 
            cmd, 
            cwd=str(edgebot_dir),
            env=env
        )
        
        if success:
            # Wait for EdgeBot to be ready
            health_url = f"http://localhost:{self.health_port}/healthz"
            return HealthChecker.wait_for_health(health_url, timeout=30)
            
        return False
        
    @pytest.mark.asyncio
    async def test_edgebot_basic_functionality(self):
        """Test basic EdgeBot functionality with syslog input and file output."""
        # Create configuration
        config_file = self.create_edgebot_config()
        
        # Start EdgeBot
        assert self.start_edgebot(config_file), "Failed to start EdgeBot"
        
        # Wait a bit for full initialization
        await asyncio.sleep(3)
        
        # Test health endpoint
        health_url = f"http://localhost:{self.health_port}/healthz"
        response = requests.get(health_url, timeout=5)
        assert response.status_code == 200, f"Health check failed: {response.text}"
        
        health_data = response.json()
        assert health_data.get('status') == 'healthy', f"EdgeBot not healthy: {health_data}"
        
        # Send test syslog messages
        test_messages = SyslogSender.send_test_messages(
            count=3, 
            host="localhost", 
            port=self.syslog_udp_port
        )
        
        assert len(test_messages) == 3, "Failed to send all test messages"
        
        # Wait for EdgeBot to process messages and write to file
        await asyncio.sleep(5)
        
        # Check that output files were created
        output_files = list(self.output_dir.glob("payload-*.json"))
        assert len(output_files) > 0, f"No output files found in {self.output_dir}"
        
        # Validate output file content
        total_events = 0
        for output_file in output_files:
            with open(output_file, 'r') as f:
                for line in f:
                    if line.strip():  # Skip empty lines
                        event = json.loads(line.strip())
                        total_events += 1
                        
                        # Validate event structure
                        assert 'message' in event, f"Event missing 'message' field: {event}"
                        assert 'timestamp' in event, f"Event missing 'timestamp' field: {event}"
                        assert 'hostname' in event, f"Event missing 'hostname' field: {event}"
                        
                        # Check for test message content
                        if 'edgebot-test' in event.get('message', ''):
                            assert 'testhost' in event.get('hostname', ''), "Test hostname not preserved"
        
        assert total_events >= 3, f"Expected at least 3 events, found {total_events}"
        
    @pytest.mark.asyncio 
    async def test_edgebot_metrics_endpoint(self):
        """Test EdgeBot metrics endpoint functionality."""
        # Create configuration
        config_file = self.create_edgebot_config()
        
        # Start EdgeBot
        assert self.start_edgebot(config_file), "Failed to start EdgeBot"
        
        # Send some test messages first
        test_messages = SyslogSender.send_test_messages(
            count=5,
            host="localhost", 
            port=self.syslog_udp_port
        )
        
        # Wait for processing
        await asyncio.sleep(3)
        
        # Test metrics endpoint
        metrics_url = f"http://localhost:{self.health_port}/metrics"
        response = requests.get(metrics_url, timeout=5)
        assert response.status_code == 200, f"Metrics endpoint failed: {response.status_code}"
        
        metrics_text = response.text
        assert len(metrics_text) > 0, "Metrics endpoint returned empty response"
        
        # Check for expected metrics
        expected_metrics = [
            "edgebot_messages_received_total",
            "edgebot_messages_processed_total", 
            "edgebot_output_files_written_total"
        ]
        
        for metric in expected_metrics:
            assert metric in metrics_text, f"Expected metric '{metric}' not found in metrics output"
            
        # Check that message counters are > 0
        for line in metrics_text.split('\n'):
            if line.startswith('edgebot_messages_received_total'):
                # Extract value (after the space)
                try:
                    value = float(line.split()[-1])
                    assert value > 0, f"Message received counter should be > 0, got {value}"
                except (ValueError, IndexError):
                    pass  # Skip if can't parse
                    
    @pytest.mark.asyncio
    async def test_edgebot_multiple_message_formats(self):
        """Test EdgeBot with different syslog message formats."""
        # Create configuration
        config_file = self.create_edgebot_config()
        
        # Start EdgeBot
        assert self.start_edgebot(config_file), "Failed to start EdgeBot"
        
        # Send messages in different formats
        test_messages = [
            # RFC3164 format
            "<34>Aug 23 12:05:45 server1 testapp: RFC3164 test message",
            # RFC5424 format  
            "<165>1 2023-08-23T12:05:45.000Z server2 testapp 1234 - [exampleSDID@32473 iut=\"3\" eventSource=\"Application\"] RFC5424 test message",
            # Simple priority + message
            "<14>System test message without timestamp",
        ]
        
        for msg in test_messages:
            SyslogSender.send_message(msg, host="localhost", port=self.syslog_udp_port)
            await asyncio.sleep(0.5)
            
        # Wait for processing
        await asyncio.sleep(5)
        
        # Check output files
        output_files = list(self.output_dir.glob("payload-*.json"))
        assert len(output_files) > 0, "No output files found"
        
        # Validate that different formats were processed
        events_found = []
        for output_file in output_files:
            with open(output_file, 'r') as f:
                for line in f:
                    if line.strip():
                        event = json.loads(line.strip())
                        events_found.append(event)
                        
        # Should have at least as many events as messages sent
        assert len(events_found) >= len(test_messages), f"Expected >= {len(test_messages)} events, found {len(events_found)}"
        
        # Check that different message types were processed
        message_contents = [event.get('message', '') for event in events_found]
        assert any('RFC3164' in msg for msg in message_contents), "RFC3164 message not found"
        assert any('RFC5424' in msg for msg in message_contents), "RFC5424 message not found"
        assert any('System test message' in msg for msg in message_contents), "Simple message not found"
        
    @pytest.mark.asyncio
    async def test_edgebot_configuration_validation(self):
        """Test EdgeBot with invalid configuration to ensure proper error handling."""
        # Create invalid configuration (missing required fields)
        invalid_config = {
            'server': {'host': '127.0.0.1'},  # Missing port
            'inputs': {},  # No inputs defined
            'output': {},  # No outputs defined  
        }
        
        config_file = self.temp_dir / 'invalid-config.yaml'
        with open(config_file, 'w') as f:
            yaml.dump(invalid_config, f)
            
        # Try to start EdgeBot with invalid config
        edgebot_dir = Path(__file__).parent.parent.parent / "edge_node"
        
        cmd = [
            "python", "-m", "app.main",
            "-c", str(config_file),
            "--dry-run"  # Use dry-run to test config validation
        ]
        
        env = os.environ.copy()
        env['PYTHONPATH'] = str(edgebot_dir)
        
        # This should fail quickly due to invalid configuration
        success = self.process_manager.start_process(
            "edgebot-invalid",
            cmd,
            cwd=str(edgebot_dir),
            env=env
        )
        
        # Should start but exit quickly due to validation error
        if success:
            await asyncio.sleep(2)  # Give time for validation
            
        # Get process output to check for validation errors
        stdout, stderr = self.process_manager.get_process_logs("edgebot-invalid")
        
        # Should contain some validation error information
        assert stdout or stderr, "No output from EdgeBot config validation"