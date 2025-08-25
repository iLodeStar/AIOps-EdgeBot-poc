"""Test sanitization logic for payload artifacts."""

import sys
import os
import json
import gzip
import tempfile
import unittest
from pathlib import Path

# Add the app directory to the path
sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

from output.shipper import build_sanitized_envelope


class TestSanitization(unittest.TestCase):
    """Test sanitization of messages before shipping."""

    def test_build_sanitized_envelope_removes_spool_id(self):
        """Test that __spool_id is removed from messages."""
        batch_messages = [
            {
                "message": "test message 1",
                "timestamp": "2025-01-01T00:00:00Z",
                "__spool_id": 123,
                "__spool_timestamp": 1234567890.0,
            },
            {
                "message": "test message 2",
                "timestamp": "2025-01-01T00:01:00Z",
                "__spool_id": 124,
                "data": {"key": "value"},
            },
        ]

        json_data = build_sanitized_envelope(batch_messages, is_retry=False)
        envelope = json.loads(json_data)

        # Check envelope structure
        self.assertIn("messages", envelope)
        self.assertIn("batch_size", envelope)
        self.assertIn("timestamp", envelope)
        self.assertIn("source", envelope)
        self.assertIn("is_retry", envelope)

        # Check messages are sanitized
        self.assertEqual(len(envelope["messages"]), 2)

        for message in envelope["messages"]:
            # Should not contain any __spool* fields
            self.assertNotIn("__spool_id", message)
            self.assertNotIn("__spool_timestamp", message)
            # Should not contain any __ prefixed fields
            for key in message.keys():
                self.assertFalse(
                    key.startswith("__"),
                    f"Found internal field {key} in sanitized message",
                )

    def test_build_sanitized_envelope_removes_internal_fields(self):
        """Test that other internal fields are removed."""
        batch_messages = [
            {
                "message": "test message",
                "timestamp": "2025-01-01T00:00:00Z",
                "status": "pending",
                "attempts": 1,
                "last_error": "some error",
                "enqueued_at": "2025-01-01T00:00:00Z",
                "valid_field": "should remain",
            }
        ]

        json_data = build_sanitized_envelope(batch_messages, is_retry=True)
        envelope = json.loads(json_data)

        message = envelope["messages"][0]

        # Should not contain internal fields
        self.assertNotIn("status", message)
        self.assertNotIn("attempts", message)
        self.assertNotIn("last_error", message)
        self.assertNotIn("enqueued_at", message)

        # Should contain valid fields
        self.assertIn("message", message)
        self.assertIn("timestamp", message)
        self.assertIn("valid_field", message)

        # Check is_retry flag
        self.assertTrue(envelope["is_retry"])

    def test_build_sanitized_envelope_preserves_valid_fields(self):
        """Test that valid fields are preserved."""
        batch_messages = [
            {
                "message": "test message",
                "timestamp": "2025-01-01T00:00:00Z",
                "severity": "INFO",
                "source_ip": "192.168.1.1",
                "data": {"nested": {"value": 42}},
                "__spool_id": 123,  # Should be removed
            }
        ]

        json_data = build_sanitized_envelope(batch_messages)
        envelope = json.loads(json_data)

        message = envelope["messages"][0]

        # Check all valid fields are preserved
        self.assertEqual(message["message"], "test message")
        self.assertEqual(message["timestamp"], "2025-01-01T00:00:00Z")
        self.assertEqual(message["severity"], "INFO")
        self.assertEqual(message["source_ip"], "192.168.1.1")
        self.assertEqual(message["data"]["nested"]["value"], 42)

        # Check internal field is removed
        self.assertNotIn("__spool_id", message)

    def test_json_and_gzip_equivalence(self):
        """Test that .json and .json.gz contain identical data after decompression."""
        batch_messages = [
            {
                "message": "test message",
                "timestamp": "2025-01-01T00:00:00Z",
                "__spool_id": 123,
                "data": {"key": "value"},
            }
        ]

        json_data = build_sanitized_envelope(batch_messages)

        # Simulate what _write_to_file does
        with tempfile.TemporaryDirectory() as temp_dir:
            # Write plain JSON
            json_path = os.path.join(temp_dir, "test.json")
            with open(json_path, "w") as f:
                f.write(json_data)

            # Write gzipped JSON
            gzip_path = os.path.join(temp_dir, "test.json.gz")
            compressed_data = gzip.compress(json_data.encode("utf-8"))
            with open(gzip_path, "wb") as f:
                f.write(compressed_data)

            # Read both files
            with open(json_path, "r") as f:
                json_content = f.read()

            with gzip.open(gzip_path, "rt", encoding="utf-8") as f:
                gzip_content = f.read()

            # They should be identical
            self.assertEqual(json_content, gzip_content)

            # Both should be valid JSON
            json_data_1 = json.loads(json_content)
            json_data_2 = json.loads(gzip_content)
            self.assertEqual(json_data_1, json_data_2)

            # Neither should contain __spool_id
            self.assertNotIn("__spool_id", json_content)
            self.assertNotIn("__spool_id", gzip_content)

    def test_empty_batch_handling(self):
        """Test handling of empty batch."""
        json_data = build_sanitized_envelope([])
        envelope = json.loads(json_data)

        self.assertEqual(envelope["messages"], [])
        self.assertEqual(envelope["batch_size"], 0)
        self.assertIn("timestamp", envelope)
        self.assertEqual(envelope["source"], "edgebot")
        self.assertFalse(envelope["is_retry"])


if __name__ == "__main__":
    unittest.main()
