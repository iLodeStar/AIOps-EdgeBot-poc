"""
Shared utilities for E2E testing of AIOps EdgeBot components.

This module provides common functionality for:
- Docker compose management
- Health endpoint polling  
- Syslog message sending
- Loki API interactions
- Process management
- Test data generation
"""
import asyncio
import json
import socket
import subprocess
import time
import tempfile
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import requests
import psutil
from datetime import datetime, timezone


class DockerComposeManager:
    """Manages Docker Compose services for E2E testing."""
    
    def __init__(self, compose_file: str, project_name: str = "edgebot-e2e"):
        self.compose_file = Path(compose_file)
        self.project_name = project_name
        self.running_services: List[str] = []
        
    def start_services(self, services: List[str] = None, timeout: int = 60) -> bool:
        """Start specified services or all services if none specified."""
        cmd = ["docker", "compose", "-f", str(self.compose_file), "-p", self.project_name, "up", "-d"]
        if services:
            cmd.extend(services)
            
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            if result.returncode == 0:
                self.running_services.extend(services or ["all"])
                return True
            else:
                print(f"Failed to start services: {result.stderr}")
                return False
        except subprocess.TimeoutExpired:
            print(f"Timeout starting services after {timeout}s")
            return False
            
    def stop_services(self, timeout: int = 30) -> bool:
        """Stop all running services."""
        if not self.running_services:
            return True
            
        cmd = ["docker", "compose", "-f", str(self.compose_file), "-p", self.project_name, "down", "-v"]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            success = result.returncode == 0
            if success:
                self.running_services.clear()
            return success
        except subprocess.TimeoutExpired:
            print(f"Timeout stopping services after {timeout}s")
            return False
            
    def get_service_logs(self, service_name: str) -> str:
        """Get logs from a specific service."""
        cmd = ["docker", "compose", "-f", str(self.compose_file), "-p", self.project_name, "logs", service_name]
        result = subprocess.run(cmd, capture_output=True, text=True)
        return result.stdout if result.returncode == 0 else ""


class HealthChecker:
    """Checks health endpoints and waits for services to be ready."""
    
    @staticmethod
    def wait_for_health(url: str, timeout: int = 60, interval: float = 1.0) -> bool:
        """Wait for a health endpoint to return 200 OK."""
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                response = requests.get(url, timeout=5)
                if response.status_code == 200:
                    return True
            except requests.RequestException:
                pass
            time.sleep(interval)
        return False
        
    @staticmethod
    def wait_for_port(host: str, port: int, timeout: int = 60) -> bool:
        """Wait for a port to be accepting connections."""
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                with socket.create_connection((host, port), timeout=1):
                    return True
            except (ConnectionRefusedError, socket.timeout, OSError):
                time.sleep(1)
        return False


class SyslogSender:
    """Sends test syslog messages via UDP."""
    
    @staticmethod
    def send_message(message: str, host: str = "localhost", port: int = 5514) -> bool:
        """Send a single syslog message via UDP."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.settimeout(5)
                sock.sendto(message.encode('utf-8'), (host, port))
                return True
        except Exception as e:
            print(f"Failed to send syslog message: {e}")
            return False
            
    @classmethod
    def send_test_messages(cls, count: int = 5, host: str = "localhost", port: int = 5514) -> List[Dict]:
        """Send multiple test syslog messages and return the sent data."""
        messages = []
        for i in range(count):
            timestamp = datetime.now().strftime("%b %d %H:%M:%S")
            facility_severity = 34  # auth.crit
            message = f"<{facility_severity}>{timestamp} testhost edgebot-test: Test message #{i+1} from E2E suite"
            
            if cls.send_message(message, host, port):
                messages.append({
                    "raw_message": message,
                    "test_id": f"e2e-test-{i+1}",
                    "timestamp": timestamp,
                    "facility": 4,
                    "severity": 2,
                    "hostname": "testhost",
                    "program": "edgebot-test"
                })
            time.sleep(0.1)  # Brief delay between messages
            
        return messages


class LokiClient:
    """Client for interacting with Loki API."""
    
    def __init__(self, base_url: str = "http://localhost:3100"):
        self.base_url = base_url.rstrip('/')
        
    def query(self, query_string: str, start_time: Optional[datetime] = None) -> Dict:
        """Execute a LogQL query against Loki."""
        url = f"{self.base_url}/loki/api/v1/query"
        
        params = {"query": query_string}
        if start_time:
            params["start"] = str(int(start_time.timestamp() * 1000000000))  # nanoseconds
            
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            print(f"Loki query failed: {e}")
            return {}
            
    def get_labels(self) -> Dict:
        """Get available labels from Loki."""
        url = f"{self.base_url}/loki/api/v1/labels"
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            print(f"Failed to get Loki labels: {e}")
            return {}
            
    def health_check(self) -> bool:
        """Check if Loki is healthy."""
        url = f"{self.base_url}/ready"
        try:
            response = requests.get(url, timeout=5)
            return response.status_code == 200
        except requests.RequestException:
            return False


class ProcessManager:
    """Manages local processes for E2E testing."""
    
    def __init__(self):
        self.processes: Dict[str, subprocess.Popen] = {}
        
    def start_process(self, name: str, cmd: List[str], cwd: str = None, env: Dict = None) -> bool:
        """Start a named process."""
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=cwd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            self.processes[name] = proc
            time.sleep(2)  # Give process time to start
            
            # Check if process is still running
            if proc.poll() is None:
                return True
            else:
                print(f"Process {name} failed to start")
                return False
        except Exception as e:
            print(f"Failed to start process {name}: {e}")
            return False
            
    def stop_process(self, name: str, timeout: int = 10) -> bool:
        """Stop a named process gracefully."""
        if name not in self.processes:
            return True
            
        proc = self.processes[name]
        if proc.poll() is not None:
            # Already terminated
            del self.processes[name]
            return True
            
        try:
            proc.terminate()
            proc.wait(timeout=timeout)
            del self.processes[name]
            return True
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            del self.processes[name]
            return True
        except Exception as e:
            print(f"Failed to stop process {name}: {e}")
            return False
            
    def stop_all(self):
        """Stop all managed processes."""
        for name in list(self.processes.keys()):
            self.stop_process(name)
            
    def get_process_logs(self, name: str) -> Tuple[str, str]:
        """Get stdout and stderr from a process."""
        if name not in self.processes:
            return "", ""
            
        proc = self.processes[name]
        try:
            stdout, stderr = proc.communicate(timeout=1)
            return stdout, stderr
        except subprocess.TimeoutExpired:
            return "", ""


class TestDataManager:
    """Manages test data and temporary directories."""
    
    def __init__(self):
        self.temp_dirs: List[Path] = []
        
    def create_temp_dir(self, prefix: str = "edgebot-e2e-") -> Path:
        """Create a temporary directory for test data."""
        temp_dir = Path(tempfile.mkdtemp(prefix=prefix))
        self.temp_dirs.append(temp_dir)
        return temp_dir
        
    def cleanup(self):
        """Clean up all temporary directories."""
        for temp_dir in self.temp_dirs:
            if temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
        self.temp_dirs.clear()
        
    @staticmethod
    def create_edgebot_config(output_dir: Path, mothership_url: str = None) -> Path:
        """Create a test EdgeBot configuration file."""
        config = {
            'server': {
                'host': '127.0.0.1',
                'port': 8080
            },
            'inputs': {
                'syslog': {
                    'enabled': True,
                    'udp_port': 5514,
                    'tcp_port': 5515
                }
            },
            'output': {},
            'observability': {
                'health_port': 8081,
                'metrics_enabled': True
            }
        }
        
        if mothership_url:
            config['output']['mothership'] = {
                'url': mothership_url,
                'batch_size': 10,
                'flush_interval_sec': 1
            }
        else:
            config['output']['file'] = {
                'enabled': True,
                'dir': str(output_dir),
                'filename_pattern': 'payload-{timestamp}.json'
            }
            
        config_file = output_dir / 'config.yaml'
        import yaml
        with open(config_file, 'w') as f:
            yaml.dump(config, f)
            
        return config_file
        
    @staticmethod
    def create_mothership_config(temp_dir: Path, loki_enabled: bool = True, tsdb_enabled: bool = False) -> Path:
        """Create a test Mothership configuration file."""
        config = {
            'server': {
                'host': '0.0.0.0',
                'port': 8443
            },
            'sinks': {
                'loki': {
                    'enabled': loki_enabled,
                    'url': 'http://localhost:3100'
                },
                'tsdb': {
                    'enabled': tsdb_enabled
                }
            },
            'pipeline': {
                'processors': [
                    {
                        'type': 'drop_fields',
                        'config': {'fields': ['_internal']}
                    },
                    {
                        'type': 'add_tags', 
                        'config': {'add_tags': {'source': 'e2e-test'}}
                    }
                ]
            }
        }
        
        config_file = temp_dir / 'mothership_config.yaml'
        import yaml
        with open(config_file, 'w') as f:
            yaml.dump(config, f)
            
        return config_file


def find_free_port(start_port: int = 8080, max_attempts: int = 100) -> int:
    """Find a free port starting from the given port."""
    for port in range(start_port, start_port + max_attempts):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('localhost', port))
                return port
        except OSError:
            continue
    raise RuntimeError(f"Could not find free port in range {start_port}-{start_port + max_attempts}")


def wait_for_file_content(file_path: Path, expected_lines: int = 1, timeout: int = 30) -> bool:
    """Wait for a file to exist and contain expected number of lines."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        if file_path.exists():
            try:
                with open(file_path, 'r') as f:
                    lines = f.readlines()
                    if len(lines) >= expected_lines:
                        return True
            except (IOError, FileNotFoundError):
                pass
        time.sleep(0.5)
    return False