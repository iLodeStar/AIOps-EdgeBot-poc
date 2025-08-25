"""Tests for pipeline processors."""

import unittest
import asyncio
from unittest.mock import MagicMock, patch
import sys
import os
from pathlib import Path

# Add the app directory to the path
sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

from pipeline.processor import Pipeline, Processor
from pipeline.processors_redaction import (
    DropFieldsProcessor,
    MaskPatternsProcessor,
    HashFieldsProcessor,
    RedactionPipeline,
    PIISafetyValidator,
)
from pipeline.processors_enrich import (
    AddTagsProcessor,
    SeverityMapProcessor,
    ServiceFromPathProcessor,
    TimestampNormalizer,
)


class TestRedactionProcessors(unittest.TestCase):
    """Test redaction processors."""

    def test_drop_fields_processor(self):
        """Test dropping sensitive fields."""
        config = {"drop_fields": ["password", "secret", "token"]}
        processor = DropFieldsProcessor(config)

        event = {
            "message": "Login attempt",
            "username": "testuser",
            "password": "secret123",
            "token": "abc123",
            "timestamp": "2025-01-01T00:00:00Z",
        }

        result = asyncio.run(processor.process(event))

        self.assertNotIn("password", result)
        self.assertNotIn("token", result)
        self.assertIn("message", result)
        self.assertIn("username", result)
        self.assertIn("timestamp", result)

    def test_mask_patterns_processor(self):
        """Test masking sensitive patterns."""
        config = {
            "mask_patterns": [r"password=\S+", r"\b\d{3}-\d{2}-\d{4}\b"],  # SSN
            "mask_char": "*",
            "mask_length": 8,
        }
        processor = MaskPatternsProcessor(config)

        event = {
            "message": "User login with password=secret123 and SSN 123-45-6789",
            "data": {"config": "password=admin123"},
        }

        result = asyncio.run(processor.process(event))

        # The exact masking depends on the pattern matching, let's check the key parts
        self.assertIn("********", result["message"])  # Password should be masked
        self.assertIn(
            "********", result["data"]["config"]
        )  # Config password should be masked

    def test_hash_fields_processor(self):
        """Test hashing sensitive fields."""
        config = {
            "hash_fields": ["username", "email"],
            "salt": "test_salt",
            "algorithm": "sha256",
        }
        processor = HashFieldsProcessor(config)

        event = {
            "username": "testuser",
            "email": "test@example.com",
            "message": "User activity",
        }

        result = asyncio.run(processor.process(event))

        # Should be hashed (not equal to original)
        self.assertNotEqual(result["username"], "testuser")
        self.assertNotEqual(result["email"], "test@example.com")

        # Should be deterministic (same input = same hash)
        result2 = asyncio.run(processor.process(event))
        self.assertEqual(result["username"], result2["username"])
        self.assertEqual(result["email"], result2["email"])

        # Message should remain unchanged
        self.assertEqual(result["message"], "User activity")

    def test_pii_safety_validator(self):
        """Test PII safety validation."""
        config = {"strict_mode": False}
        validator = PIISafetyValidator(config)

        # Safe event (no PII)
        safe_event = {
            "message": "User logged in successfully",
            "username": "hashed_user_123",
            "severity": "info",
        }

        result = asyncio.run(validator.process(safe_event))
        self.assertEqual(result, safe_event)

        # Event with PII (should log warning in non-strict mode)
        pii_event = {
            "message": "Login failed for user@example.com",
            "phone": "123-456-7890",
        }

        # Should not raise exception in non-strict mode
        result = asyncio.run(validator.process(pii_event))
        self.assertEqual(result, pii_event)


class TestEnrichmentProcessors(unittest.TestCase):
    """Test enrichment processors."""

    def test_add_tags_processor(self):
        """Test adding static tags."""
        config = {
            "add_tags": {
                "processed_by": "mothership",
                "version": "1.5",
                "environment": "test",
            }
        }
        processor = AddTagsProcessor(config)

        event = {"message": "Test event"}

        result = asyncio.run(processor.process(event))

        self.assertIn("tags", result)
        self.assertEqual(result["tags"]["processed_by"], "mothership")
        self.assertEqual(result["tags"]["version"], "1.5")
        self.assertEqual(result["tags"]["environment"], "test")

    def test_severity_map_processor(self):
        """Test severity mapping."""
        config = {
            "severity_mapping": {"critical": 2, "error": 3, "warning": 4, "info": 6}
        }
        processor = SeverityMapProcessor(config)

        test_cases = [
            ({"severity": "critical"}, 2),
            ({"severity": "CRITICAL"}, 2),  # Case insensitive
            ({"severity": "error"}, 3),
            ({"severity": "4"}, 4),  # Numeric string
        ]

        for event, expected_num in test_cases:
            result = asyncio.run(processor.process(event))
            self.assertEqual(result["severity_num"], expected_num)

    def test_service_from_path_processor(self):
        """Test service extraction from paths."""
        config = {
            "path_patterns": [
                (r"/var/log/nginx/", "nginx"),
                (r"/var/log/mysql/", "mysql"),
                (r"/opt/([^/]+)/", r"\1"),
            ]
        }
        processor = ServiceFromPathProcessor(config)

        test_cases = [
            ({"path": "/var/log/nginx/access.log"}, "nginx"),
            ({"path": "/var/log/mysql/error.log"}, "mysql"),
            ({"path": "/opt/myapp/app.log"}, "myapp"),
            ({"hostname": "web-server-01"}, "web-server-01"),
        ]

        for event, expected_service in test_cases:
            result = asyncio.run(processor.process(event))
            if expected_service:
                self.assertEqual(result["service"], expected_service)

    def test_timestamp_normalizer(self):
        """Test timestamp normalization."""
        config = {"timestamp_fields": ["timestamp", "time"]}
        processor = TimestampNormalizer(config)

        # Test with Unix timestamp
        event = {"time": 1640995200}  # 2022-01-01 00:00:00 UTC
        result = asyncio.run(processor.process(event))
        self.assertIn("T", result["time"])  # Should be ISO format

        # Test with ISO string
        event = {"timestamp": "2022-01-01T00:00:00Z"}
        result = asyncio.run(processor.process(event))
        self.assertEqual(result["timestamp"], "2022-01-01T00:00:00Z")

        # Test with missing timestamp (should add current)
        event = {"message": "test"}
        result = asyncio.run(processor.process(event))
        self.assertIn("timestamp", result)


class TestPipeline(unittest.TestCase):
    """Test pipeline orchestration."""

    def test_pipeline_execution_order(self):
        """Test that processors execute in correct order."""
        config = {}
        pipeline = Pipeline(config)

        # Create test processors
        drop_processor = DropFieldsProcessor({"drop_fields": ["secret"]})
        tags_processor = AddTagsProcessor({"add_tags": {"processed": "true"}})

        # Add processors
        pipeline.add_processor(drop_processor)
        pipeline.add_processor(tags_processor)

        # Test event
        event = {"message": "test message", "secret": "should_be_removed"}

        result = asyncio.run(pipeline.process_single_event(event))

        # Secret should be dropped (first processor)
        self.assertNotIn("secret", result)

        # Tag should be added (second processor)
        self.assertIn("tags", result)
        self.assertEqual(result["tags"]["processed"], "true")

    def test_pipeline_batch_processing(self):
        """Test batch processing."""
        config = {}
        pipeline = Pipeline(config)

        # Add a simple processor
        tags_processor = AddTagsProcessor({"add_tags": {"batch_processed": "true"}})
        pipeline.add_processor(tags_processor)

        # Test events
        events = [
            {"message": "event 1"},
            {"message": "event 2"},
            {"message": "event 3"},
        ]

        results = asyncio.run(pipeline.process_events(events))

        self.assertEqual(len(results), 3)
        for result in results:
            self.assertEqual(result["tags"]["batch_processed"], "true")

    def test_pipeline_stats(self):
        """Test pipeline statistics."""
        config = {}
        pipeline = Pipeline(config)

        # Add processor
        processor = AddTagsProcessor({"add_tags": {"test": "true"}})
        pipeline.add_processor(processor)

        # Process some events
        events = [{"message": f"event {i}"} for i in range(5)]
        asyncio.run(pipeline.process_events(events))

        stats = pipeline.get_stats()

        self.assertEqual(stats["total_events"], 5)
        self.assertEqual(stats["successful_events"], 5)
        self.assertIn("processors", stats)
        self.assertIn("AddTags", stats["processors"])


if __name__ == "__main__":
    unittest.main()
