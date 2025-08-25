"""Deterministic redaction processors - applied BEFORE any LLM processing for PII safety."""

import re
import hashlib
from typing import Dict, Any, List, Optional, Union
import structlog
from .processor import Processor, ProcessingContext

logger = structlog.get_logger()


class DropFieldsProcessor(Processor):
    """Processor that drops specified fields from events."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config, "DropFields")
        self.drop_fields = config.get("drop_fields", [])
        logger.info(
            f"Initialized DropFields processor", fields_to_drop=self.drop_fields
        )

    async def process(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Drop specified fields from the event."""
        if not self.drop_fields:
            return event

        processed_event = event.copy()
        dropped_fields = []

        for field in self.drop_fields:
            if field in processed_event:
                del processed_event[field]
                dropped_fields.append(field)

        if dropped_fields:
            logger.debug("Dropped fields", dropped_fields=dropped_fields)

        return processed_event


class MaskPatternsProcessor(Processor):
    """Processor that masks sensitive patterns in string values."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config, "MaskPatterns")
        patterns = config.get("mask_patterns", [])
        self.compiled_patterns = []

        for pattern in patterns:
            try:
                compiled = re.compile(pattern, re.IGNORECASE)
                self.compiled_patterns.append((pattern, compiled))
            except re.error as e:
                logger.warning(f"Invalid regex pattern: {pattern}", error=str(e))

        self.mask_char = config.get("mask_char", "*")
        self.mask_length = config.get("mask_length", 8)

        logger.info(
            f"Initialized MaskPatterns processor", patterns=len(self.compiled_patterns)
        )

    async def process(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Mask sensitive patterns in the event."""
        processed_event = self._mask_recursive(event)
        return processed_event

    def _mask_recursive(self, obj: Any) -> Any:
        """Recursively mask patterns in nested objects."""
        if isinstance(obj, dict):
            return {k: self._mask_recursive(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._mask_recursive(item) for item in obj]
        elif isinstance(obj, str):
            return self._mask_string(obj)
        else:
            return obj

    def _mask_string(self, text: str) -> str:
        """Mask sensitive patterns in a string."""
        masked_text = text

        for pattern_str, compiled_pattern in self.compiled_patterns:

            def replace_match(match):
                # Replace with mask characters, preserving length if reasonable
                original_length = len(match.group(0))
                if original_length <= self.mask_length * 2:
                    return self.mask_char * min(original_length, self.mask_length)
                else:
                    return self.mask_char * self.mask_length

            masked_text = compiled_pattern.sub(replace_match, masked_text)

        return masked_text


class HashFieldsProcessor(Processor):
    """Processor that hashes specified fields for pseudonymization."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config, "HashFields")
        self.hash_fields = config.get("hash_fields", [])
        self.salt = config.get("salt", "mothership_default_salt")
        self.hash_algorithm = config.get("algorithm", "sha256")
        self.preserve_original = config.get("preserve_original", False)

        logger.info(
            f"Initialized HashFields processor",
            fields_to_hash=self.hash_fields,
            algorithm=self.hash_algorithm,
            preserve_original=self.preserve_original,
        )

    async def process(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Hash specified fields in the event."""
        if not self.hash_fields:
            return event

        processed_event = event.copy()
        hashed_fields = []

        for field in self.hash_fields:
            if field in processed_event:
                original_value = processed_event[field]
                if original_value is not None:
                    hashed_value = self._hash_value(str(original_value))

                    if self.preserve_original:
                        processed_event[f"{field}_original"] = original_value

                    processed_event[field] = hashed_value
                    hashed_fields.append(field)

        if hashed_fields:
            logger.debug("Hashed fields", hashed_fields=hashed_fields)

        return processed_event

    def _hash_value(self, value: str) -> str:
        """Hash a string value with salt."""
        salted_value = f"{self.salt}{value}"

        if self.hash_algorithm == "md5":
            return hashlib.md5(salted_value.encode()).hexdigest()
        elif self.hash_algorithm == "sha1":
            return hashlib.sha1(salted_value.encode()).hexdigest()
        elif self.hash_algorithm == "sha256":
            return hashlib.sha256(salted_value.encode()).hexdigest()
        else:
            logger.warning(
                f"Unknown hash algorithm: {self.hash_algorithm}, using sha256"
            )
            return hashlib.sha256(salted_value.encode()).hexdigest()


class RedactionPipeline(Processor):
    """Composite processor that applies all redaction steps in sequence."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config, "RedactionPipeline")

        # Initialize sub-processors
        self.processors = []

        redaction_config = config.get("redaction", {})

        # Drop fields processor
        if redaction_config.get("drop_fields"):
            drop_config = {"drop_fields": redaction_config["drop_fields"]}
            self.processors.append(DropFieldsProcessor(drop_config))

        # Mask patterns processor
        if redaction_config.get("mask_patterns"):
            mask_config = {
                "mask_patterns": redaction_config["mask_patterns"],
                "mask_char": redaction_config.get("mask_char", "*"),
                "mask_length": redaction_config.get("mask_length", 8),
            }
            self.processors.append(MaskPatternsProcessor(mask_config))

        # Hash fields processor
        if redaction_config.get("hash_fields"):
            hash_config = {
                "hash_fields": redaction_config["hash_fields"],
                "salt": redaction_config.get("salt", "mothership_default_salt"),
                "algorithm": redaction_config.get("hash_algorithm", "sha256"),
                "preserve_original": redaction_config.get("preserve_original", False),
            }
            self.processors.append(HashFieldsProcessor(hash_config))

        logger.info(
            f"Initialized RedactionPipeline",
            sub_processors=[p.name for p in self.processors],
        )

    async def process(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Apply all redaction processors in sequence."""
        current_event = event

        for processor in self.processors:
            current_event = await processor.process(current_event)
            # Update stats from sub-processors
            sub_stats = processor.get_stats()
            self.stats["processed"] += sub_stats.get("processed", 0)
            self.stats["errors"] += sub_stats.get("errors", 0)

        return current_event

    async def process_batch(self, events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Process batch through all redaction processors."""
        current_events = events

        for processor in self.processors:
            current_events = await processor.process_batch(current_events)

        return current_events


class PIISafetyValidator(Processor):
    """Validator that checks if PII has been properly redacted before LLM processing."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config, "PIISafetyValidator")

        # PII patterns to detect
        self.pii_patterns = [
            (r"\b\d{3}-\d{2}-\d{4}\b", "SSN"),  # US Social Security Number
            (
                r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b",
                "Credit Card",
            ),  # Credit card
            (r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", "Email"),  # Email
            (r"\b\d{3}-\d{3}-\d{4}\b", "Phone"),  # US Phone number
            (r"password\s*[=:]\s*\S+", "Password"),  # Password field
            (r"token\s*[=:]\s*\S+", "Token"),  # Token field
        ]

        self.compiled_patterns = []
        for pattern, name in self.pii_patterns:
            try:
                compiled = re.compile(pattern, re.IGNORECASE)
                self.compiled_patterns.append((compiled, name))
            except re.error as e:
                logger.warning(f"Invalid PII pattern: {pattern}", error=str(e))

        self.strict_mode = config.get("strict_mode", True)
        logger.info(
            f"Initialized PIISafetyValidator",
            patterns=len(self.compiled_patterns),
            strict_mode=self.strict_mode,
        )

    async def process(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Validate that PII has been properly redacted."""
        pii_found = self._detect_pii(event)

        if pii_found:
            if self.strict_mode:
                # In strict mode, fail the event
                logger.error(
                    "PII detected in event after redaction",
                    pii_types=[pii[1] for pii in pii_found],
                )
                raise ValueError(
                    f"PII safety violation: {[pii[1] for pii in pii_found]}"
                )
            else:
                # In non-strict mode, just log warning
                logger.warning(
                    "PII detected in event after redaction",
                    pii_types=[pii[1] for pii in pii_found],
                )

        return event

    def _detect_pii(self, obj: Any, path: str = "") -> List[tuple]:
        """Recursively detect PII in nested objects."""
        found_pii = []

        if isinstance(obj, dict):
            for k, v in obj.items():
                found_pii.extend(self._detect_pii(v, f"{path}.{k}" if path else k))
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                found_pii.extend(self._detect_pii(item, f"{path}[{i}]"))
        elif isinstance(obj, str):
            for pattern, name in self.compiled_patterns:
                if pattern.search(obj):
                    found_pii.append((path, name, obj))

        return found_pii
