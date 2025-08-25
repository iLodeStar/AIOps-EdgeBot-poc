"""Basic tests for EdgeBot configuration and syslog parsing."""

import unittest
import tempfile
import yaml
from pathlib import Path
import sys

# Add the app directory to the path
sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

from config import ConfigManager
from inputs.syslog_server import SyslogParser


class TestConfig(unittest.TestCase):
    """Test configuration management."""

    def test_default_config(self):
        """Test default configuration loading."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(
                {
                    "server": {"host": "127.0.0.1", "port": 8080},
                    "inputs": {"syslog": {"enabled": True}},
                    "output": {"mothership": {"url": "https://test.com/ingest"}},
                    "observability": {"health_port": 8081},
                },
                f,
            )
            config_path = f.name

        try:
            config_manager = ConfigManager(config_path)
            config = config_manager.load_config()

            self.assertEqual(config["server"]["host"], "127.0.0.1")
            self.assertTrue(config["inputs"]["syslog"]["enabled"])

        finally:
            Path(config_path).unlink()

    def test_env_overrides(self):
        """Test environment variable overrides."""
        import os

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(
                {
                    "server": {"host": "0.0.0.0", "port": 8080},
                    "inputs": {"syslog": {"enabled": True, "udp_port": 5514}},
                    "output": {"mothership": {"url": "https://test.com/ingest"}},
                    "observability": {"health_port": 8081},
                },
                f,
            )
            config_path = f.name

        # Set environment variables
        os.environ["EDGEBOT_HOST"] = "192.168.1.1"
        os.environ["EDGEBOT_SYSLOG_UDP_PORT"] = "9999"

        try:
            config_manager = ConfigManager(config_path)
            config = config_manager.load_config()

            self.assertEqual(config["server"]["host"], "192.168.1.1")
            self.assertEqual(config["inputs"]["syslog"]["udp_port"], 9999)

        finally:
            Path(config_path).unlink()
            # Clean up environment
            os.environ.pop("EDGEBOT_HOST", None)
            os.environ.pop("EDGEBOT_SYSLOG_UDP_PORT", None)


class TestSyslogParser(unittest.TestCase):
    """Test syslog message parsing."""

    def test_rfc3164_parsing(self):
        """Test RFC3164 syslog message parsing."""
        message = "<34>Oct 11 22:14:15 mymachine su: 'su root' failed for lonvick on /dev/pts/8"
        client_addr = ("192.168.1.1", 12345)

        result = SyslogParser.parse_message(message, client_addr)

        self.assertEqual(result["rfc_variant"], "rfc3164")
        self.assertEqual(result["facility"], "security")
        self.assertEqual(result["severity"], "critical")
        self.assertEqual(result["hostname"], "mymachine")
        self.assertEqual(result["tag"], "su")
        self.assertIn("'su root' failed for lonvick on /dev/pts/8", result["message"])

    def test_rfc5424_parsing(self):
        """Test RFC5424 syslog message parsing."""
        message = "<165>1 2003-08-24T05:14:15.000003-07:00 192.0.2.1 myproc 8710 - - %% It's time to make the do-nuts."
        client_addr = ("192.168.1.1", 12345)

        result = SyslogParser.parse_message(message, client_addr)

        self.assertEqual(result["rfc_variant"], "rfc5424")
        self.assertEqual(result["facility"], "local4")
        self.assertEqual(result["severity"], "notice")
        self.assertEqual(result["hostname"], "192.0.2.1")
        self.assertEqual(result["app_name"], "myproc")
        self.assertIn("It's time to make the do-nuts.", result["message"])

    def test_priority_parsing(self):
        """Test priority value parsing."""
        facility, severity, facility_name, severity_name = SyslogParser.parse_priority(
            165
        )

        self.assertEqual(facility, 20)  # local4
        self.assertEqual(severity, 5)  # notice
        self.assertEqual(facility_name, "local4")
        self.assertEqual(severity_name, "notice")

    def test_malformed_message(self):
        """Test parsing of malformed syslog message."""
        message = "This is not a valid syslog message"
        client_addr = ("192.168.1.1", 12345)

        result = SyslogParser.parse_message(message, client_addr)

        self.assertEqual(result["rfc_variant"], "unknown")
        self.assertIn("parse_error", result)
        self.assertEqual(result["message"], message)


if __name__ == "__main__":
    unittest.main()
