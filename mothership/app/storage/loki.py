"""Loki log storage client with batching and safe labeling."""

import asyncio
import json
import os
import time
from typing import Dict, Any, List, Optional, Set
from datetime import datetime, timezone
import httpx
import structlog

logger = structlog.get_logger(__name__)


class LokiClient:
    """Async Loki client that batches events and pushes to /loki/api/v1/push."""

    # Safe labels that won't cause high cardinality issues
    SAFE_LABELS = {
        "type",
        "service",
        "host",
        "site",
        "env",
        "severity",
        "level",
        "source",
    }

    # Labels to avoid due to high cardinality
    HIGH_CARDINALITY_LABELS = {
        "timestamp",
        "id",
        "uuid",
        "session_id",
        "request_id",
        "trace_id",
        "ip",
        "user_id",
        "filename",
        "line",
        "pid",
        "thread_id",
    }

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.client: Optional[httpx.AsyncClient] = None
        self._batch_queue: List[Dict[str, Any]] = []
        self._batch_lock = asyncio.Lock()
        self._last_flush = time.time()
        self._running = False
        self._flush_task: Optional[asyncio.Task] = None

    async def start(self):
        """Start the Loki client and batch processing."""
        if not self.config.get("enabled", False):
            logger.debug("Loki client disabled, not starting")
            return

        # Configure HTTP client
        auth = None
        if self.config.get("username") and self.config.get("password"):
            auth = (self.config["username"], self.config["password"])

        headers = {"Content-Type": "application/json"}
        if self.config.get("tenant_id"):
            headers["X-Scope-OrgID"] = self.config["tenant_id"]

        self.client = httpx.AsyncClient(
            auth=auth, headers=headers, timeout=self.config.get("timeout_seconds", 30.0)
        )

        # Start background flush task
        self._running = True
        self._flush_task = asyncio.create_task(self._flush_loop())

        logger.info(
            "Loki client started",
            url=self.config.get("url", "http://localhost:3100"),
            batch_size=self.config.get("batch_size", 100),
            has_auth=bool(auth),
            tenant_id=self.config.get("tenant_id"),
        )

    async def stop(self):
        """Stop the Loki client and flush remaining events."""
        self._running = False

        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass

        # Final flush
        await self._flush_batch(force=True)

        if self.client:
            await self.client.aclose()

        logger.info("Loki client stopped")

    async def write_events(self, events: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Write events to Loki, returning stats."""
        if not self.config.get("enabled", False) or not events:
            return {"written": 0, "queued": 0, "errors": 0}

        written = 0
        queued = 0
        errors = 0

        async with self._batch_lock:
            for event in events:
                try:
                    loki_entry = self._convert_to_loki_entry(event)
                    if loki_entry:
                        self._batch_queue.append(loki_entry)
                        queued += 1
                    else:
                        errors += 1
                except Exception as e:
                    logger.warning(
                        "Failed to convert event to Loki format",
                        error=str(e),
                        event_keys=list(event.keys()),
                    )
                    errors += 1

            # Flush if batch is full OR if it's a small batch in CI environment
            # Also flush immediately for any environment with LOKI_ENABLED=true
            is_ci_like = (
                self._is_ci_environment() or os.getenv("LOKI_ENABLED") == "true"
            )
            should_flush = len(self._batch_queue) >= self.config.get(
                "batch_size", 100
            ) or (len(self._batch_queue) > 0 and is_ci_like)

            if should_flush:
                flush_result = await self._flush_batch()
                written = flush_result.get("written", 0)
                # Include flush errors in the total error count
                flush_errors = flush_result.get("errors", 0)
                errors += flush_errors

                # If flush failed but we had queued events, adjust counts appropriately
                # In CI environment, we attempted immediate flush, so queued count should be
                # reduced by the number of events that were attempted to be flushed
                if flush_errors > 0 and written == 0:
                    # Failed to flush any events, but they were attempted
                    logger.warning(
                        "Failed to flush events to Loki in CI-like environment",
                        attempted=flush_errors,
                        queued_before_flush=queued,
                        is_ci_like=is_ci_like,
                    )

        return {"written": written, "queued": queued, "errors": errors}

    def _is_ci_environment(self) -> bool:
        """Check if we're running in a CI environment where immediate flushing is preferred."""
        # Check for GitHub Actions OR any environment with immediate flush needs
        github_actions = os.getenv("GITHUB_ACTIONS") == "true"
        mothership_ci = os.getenv("MOTHERSHIP_LOG_LEVEL") == "INFO" and not os.getenv(
            "PYTEST_CURRENT_TEST"
        )

        # Also consider any case where Loki is enabled and we want immediate results
        # This covers the regression test scenario and similar CI environments
        loki_immediate_mode = (
            self.config.get("enabled", False)
            and os.getenv("LOKI_ENABLED") == "true"
            and (github_actions or mothership_ci)
        )

        return loki_immediate_mode

    async def _wait_for_loki_ready(self, max_attempts: int = 30) -> bool:
        """Wait for Loki to be ready for ingestion in CI environments."""
        if not self._is_ci_environment():
            return True  # Skip readiness check in non-CI environments

        ready_url = (
            f"{self.config.get('url', 'http://localhost:3100').rstrip('/')}/ready"
        )
        push_url = f"{self.config.get('url', 'http://localhost:3100').rstrip('/')}/loki/api/v1/push"

        # Test both readiness endpoint and a test push to ensure Loki is truly ready
        test_payload = {
            "streams": [
                {
                    "stream": {"test": "readiness"},
                    "values": [["1000000000000000000", "readiness test"]],
                }
            ]
        }

        for attempt in range(max_attempts):
            try:
                if self.client:
                    # First check readiness endpoint with longer timeout for CI
                    ready_response = await self.client.get(ready_url, timeout=10.0)
                    if ready_response.status_code != 200:
                        logger.debug(
                            "Loki /ready endpoint not ready",
                            attempt=attempt,
                            status=ready_response.status_code,
                        )
                        continue

                    # Then test actual push endpoint with small test payload
                    push_response = await self.client.post(
                        push_url, json=test_payload, timeout=10.0
                    )
                    if push_response.status_code == 204:
                        logger.info(
                            "Loki confirmed ready for ingestion",
                            attempt=attempt,
                            total_wait_time=attempt * 1.0,
                        )
                        return True
                    else:
                        logger.debug(
                            "Loki push endpoint not ready",
                            attempt=attempt,
                            status=push_response.status_code,
                        )

                else:
                    # If client not initialized, try with a temporary client
                    async with httpx.AsyncClient(timeout=10.0) as temp_client:
                        ready_response = await temp_client.get(ready_url)
                        if ready_response.status_code != 200:
                            continue

                        push_response = await temp_client.post(
                            push_url, json=test_payload
                        )
                        if push_response.status_code == 204:
                            logger.info(
                                "Loki confirmed ready for ingestion",
                                attempt=attempt,
                                total_wait_time=attempt * 1.0,
                            )
                            return True

            except Exception as e:
                logger.debug(
                    "Loki readiness check failed", attempt=attempt, error=str(e)
                )

            if attempt < max_attempts - 1:
                await asyncio.sleep(
                    1.0
                )  # Wait 1 second between attempts for CI stability

        logger.warning(
            "Loki readiness check failed after all attempts",
            max_attempts=max_attempts,
            total_wait_time=max_attempts,
        )
        return False

    def _convert_to_loki_entry(self, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Convert an event to Loki log entry format with safe labeling."""
        try:
            # Extract timestamp
            timestamp_ns = self._extract_timestamp_ns(event)

            # Build safe labels
            labels = self._extract_safe_labels(event)

            # Build log line (everything not in labels)
            log_data = {
                k: v
                for k, v in event.items()
                if k not in labels and not k.startswith("_")
            }

            # Create log line
            if "message" in log_data:
                line = str(log_data.pop("message"))
                if log_data:
                    # Append additional fields as structured data
                    line += " " + json.dumps(log_data, separators=(",", ":"))
            else:
                line = json.dumps(log_data, separators=(",", ":"))

            return {"timestamp": str(timestamp_ns), "line": line, "labels": labels}

        except Exception as e:
            logger.warning(
                "Failed to convert event to Loki entry", error=str(e), event=event
            )
            return None

    def _extract_timestamp_ns(self, event: Dict[str, Any]) -> int:
        """Extract timestamp in nanoseconds."""
        # Try various timestamp fields
        for field in ["timestamp", "@timestamp", "time", "ts"]:
            if field in event:
                ts_value = event[field]
                if isinstance(ts_value, (int, float)):
                    # Assume seconds, convert to nanoseconds
                    return int(ts_value * 1_000_000_000)
                elif isinstance(ts_value, str):
                    try:
                        dt = datetime.fromisoformat(ts_value.replace("Z", "+00:00"))
                        return int(dt.timestamp() * 1_000_000_000)
                    except ValueError:
                        continue

        # Fallback to current time
        return int(time.time() * 1_000_000_000)

    def _extract_safe_labels(self, event: Dict[str, Any]) -> Dict[str, str]:
        """Extract safe labels to avoid high cardinality."""
        labels = {}

        for key, value in event.items():
            if key in self.SAFE_LABELS and key not in self.HIGH_CARDINALITY_LABELS:
                # Skip None values
                if value is None:
                    continue

                # Convert to string and sanitize
                label_value = str(value).strip()
                if label_value and len(label_value) <= 1024:  # Reasonable limit
                    # Sanitize label value (alphanumeric, dash, underscore, dot)
                    sanitized = "".join(
                        c if c.isalnum() or c in "-_." else "_" for c in label_value
                    )
                    if sanitized:
                        labels[key] = sanitized

        # Add default labels if missing or None
        if "service" not in labels:
            labels["service"] = "edgebot"
        if "source" not in labels or labels.get("source") in ["None", "null", ""]:
            labels["source"] = "mothership"

        return labels

    async def _flush_loop(self):
        """Background task to flush batches periodically."""
        while self._running:
            try:
                await asyncio.sleep(1.0)  # Check every second

                current_time = time.time()
                should_flush = len(
                    self._batch_queue
                ) > 0 and current_time - self._last_flush >= self.config.get(
                    "batch_timeout_seconds", 5.0
                )

                if should_flush:
                    async with self._batch_lock:
                        await self._flush_batch()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in Loki flush loop", error=str(e))
                await asyncio.sleep(5.0)  # Back off on errors

    async def _flush_batch(self, force: bool = False) -> Dict[str, Any]:
        """Flush current batch to Loki."""
        if not self._batch_queue and not force:
            return {"written": 0, "errors": 0}

        batch = self._batch_queue.copy()
        self._batch_queue.clear()
        self._last_flush = time.time()

        if not batch:
            return {"written": 0, "errors": 0}

        return await self._send_to_loki(batch)

    async def _send_to_loki(self, entries: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Send entries to Loki API."""
        if not self.client or not entries:
            return {"written": 0, "errors": len(entries)}

        # In CI environment, wait for Loki to be ready before attempting to send
        # But proceed with actual send attempt even if readiness check fails
        loki_ready = True  # Default to ready for non-CI environments
        if self._is_ci_environment():
            loki_ready = await self._wait_for_loki_ready()
            if not loki_ready:
                logger.warning(
                    "Loki readiness check failed, but proceeding with send attempt in CI environment. "
                    "If the following write attempts fail, it's likely due to Loki not being truly ready for ingestion."
                )
                # Add extra delay to give Loki more time in case readiness check was premature
                await asyncio.sleep(2.0)

        # Group entries by labels
        streams = {}
        for entry in entries:
            labels_key = json.dumps(entry["labels"], sort_keys=True)
            if labels_key not in streams:
                streams[labels_key] = {"stream": entry["labels"], "values": []}
            streams[labels_key]["values"].append([entry["timestamp"], entry["line"]])

        # Sort values by timestamp within each stream
        for stream_data in streams.values():
            stream_data["values"].sort(key=lambda x: int(x[0]))

        payload = {"streams": list(streams.values())}

        # Send to Loki with retries and improved error handling
        last_error = None
        # Use more retries in CI environment to handle potential timing issues
        # Also add extra retries for any Loki-enabled CI-like environment
        is_ci_like = self._is_ci_environment() or os.getenv("LOKI_ENABLED") == "true"
        max_retries = self.config.get("max_retries", 12 if is_ci_like else 3)

        # Add initial delay for CI environments to let Loki stabilize
        if is_ci_like:
            await asyncio.sleep(1.0)  # Give Loki a moment to be truly ready

        for attempt in range(max_retries + 1):
            try:
                url = f"{self.config.get('url', 'http://localhost:3100').rstrip('/')}/loki/api/v1/push"

                # Use longer timeout for CI environments to handle potential network delays
                timeout = (
                    20.0 if is_ci_like else self.config.get("timeout_seconds", 30.0)
                )

                response = await self.client.post(url, json=payload, timeout=timeout)

                if response.status_code == 204:
                    success_msg = "Batch sent to Loki successfully"
                    if is_ci_like:
                        success_msg += " (CI-like environment)"
                    logger.info(
                        success_msg,
                        entries=len(entries),
                        streams=len(streams),
                        attempt=attempt,
                        readiness_check_passed=loki_ready,
                        ci_like=is_ci_like,
                    )
                    return {"written": len(entries), "errors": 0}
                else:
                    error_msg = f"Unexpected status {response.status_code}"
                    if response.text:
                        error_msg += f": {response.text}"
                    raise httpx.HTTPStatusError(
                        error_msg, request=response.request, response=response
                    )

            except Exception as e:
                last_error = e

                # Provide detailed error information for debugging
                error_details = {
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                    "url": url,
                    "attempt": attempt,
                    "max_retries": max_retries,
                    "ci_like": is_ci_like,
                    "entries_count": len(entries),
                }

                # Add more specific error context
                if hasattr(e, "response"):
                    error_details["response_status"] = getattr(
                        e.response, "status_code", None
                    )
                    error_details["response_text"] = getattr(e.response, "text", None)

                if attempt < max_retries:
                    # Use exponential backoff with jitter for better reliability
                    base_backoff = self.config.get(
                        "retry_backoff_seconds",
                        2.0 if is_ci_like else 1.0,
                    )
                    backoff = base_backoff * (2**attempt) + (
                        0.1 * attempt
                    )  # Add jitter

                    logger.warning(
                        "Loki request failed, retrying",
                        backoff=backoff,
                        **error_details,
                    )
                    await asyncio.sleep(backoff)
                else:
                    # Final failure - provide comprehensive error information
                    error_msg = "Loki request failed after all retries"
                    if is_ci_like:
                        error_msg += " (CI-like environment) - This will cause query validation to fail"

                    logger.error(
                        error_msg,
                        readiness_check_passed=loki_ready,
                        total_attempts=attempt + 1,
                        **error_details,
                    )

        # All retries failed
        return {"written": 0, "errors": len(entries)}
