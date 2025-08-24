"""Storage sinks manager for dual writes to TimescaleDB and Loki."""

import asyncio
from typing import Dict, Any, List, Optional
from abc import ABC, abstractmethod
import structlog

from .protocols import StorageSink
from .loki import LokiClient
from .resilient_sink import ResilientSink
from ..metrics import mship_sink_write_seconds
from .tsdb import TimescaleDBWriter

logger = structlog.get_logger(__name__)


class TSDBSink:
    """TimescaleDB sink that uses TimescaleDBWriter for real inserts."""

    def __init__(
        self,
        config: Dict[str, Any],
        writer: Optional[TimescaleDBWriter] = None,
        db_config: Optional[Dict[str, Any]] = None,
    ):
        self.config = config or {}
        self._healthy = False
        self._owns_writer = False
        if writer is not None:
            self.writer = writer
        else:
            # Create our own writer from database config if provided
            if not db_config:
                db_config = {}
            self.writer = TimescaleDBWriter(db_config)
            self._owns_writer = True

    async def start(self):
        if not self.config.get("enabled", True):
            logger.debug("TSDB sink disabled, not starting")
            return
        if self._owns_writer:
            await self.writer.initialize()
        self._healthy = True
        logger.info("TSDB sink started", enabled=self.config.get("enabled", True))

    async def stop(self):
        if self._owns_writer and getattr(self, "writer", None):
            await self.writer.close()
        self._healthy = False
        logger.info("TSDB sink stopped")

    async def write_events(self, events: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not self.config.get("enabled", True) or not events:
            return {"written": 0, "errors": 0}
        try:
            # Check if writer is properly initialized
            if not hasattr(self.writer, "pool") or self.writer.pool is None:
                logger.warning("TSDB writer not initialized, cannot write events")
                return {"written": 0, "errors": len(events)}
            await self.writer.insert_events(events)
            return {"written": len(events), "errors": 0}
        except Exception as e:
            logger.error("TSDB write failed", error=str(e))
            return {"written": 0, "errors": len(events)}

    async def health_check(self) -> bool:
        try:
            # Consider healthy if writer is healthy and sink enabled
            if not self.config.get("enabled", True):
                return False
            # Check if writer is properly initialized before calling health_check
            if not hasattr(self.writer, "pool") or self.writer.pool is None:
                return False
            return await self.writer.health_check()
        except Exception:
            return False

    def is_enabled(self) -> bool:
        return self.config.get("enabled", True)

    def is_healthy(self) -> bool:
        return self._healthy and self.config.get("enabled", True)


class LokiSink:
    """Loki sink wrapper."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.client = LokiClient(config)

    async def start(self):
        await self.client.start()

    async def stop(self):
        await self.client.stop()

    async def write_events(self, events: List[Dict[str, Any]]) -> Dict[str, Any]:
        return await self.client.write_events(events)

    async def health_check(self) -> bool:
        return self.config.get("enabled", False)

    def is_enabled(self) -> bool:
        return self.config.get("enabled", False)

    def is_healthy(self) -> bool:
        return self.config.get("enabled", False)


class SinksManager:
    """Manages writes to multiple storage sinks with reliability features."""

    def __init__(
        self, config: Dict[str, Any], tsdb_writer: Optional[TimescaleDBWriter] = None
    ):
        self.config = config
        self.sinks: Dict[str, ResilientSink] = {}

        sinks_config = config.get("sinks", {})

        # TimescaleDB sink using the provided writer (from app startup) if available
        if sinks_config.get("timescaledb", {}).get("enabled", True) and tsdb_writer is not None:
            tsdb_config = sinks_config.get("timescaledb", {})
            db_config = config.get("database", {})
            tsdb_sink = TSDBSink(tsdb_config, writer=tsdb_writer, db_config=db_config)
            self.sinks["tsdb"] = ResilientSink("tsdb", tsdb_sink, tsdb_config)
        elif sinks_config.get("timescaledb", {}).get("enabled", True):
            logger.warning("TimescaleDB sink enabled but no writer available, disabling TSDB sink")

        # Loki sink
        if sinks_config.get("loki", {}).get("enabled", False):
            loki_config = sinks_config.get("loki", {})
            loki_sink = LokiSink(loki_config)
            self.sinks["loki"] = ResilientSink("loki", loki_sink, loki_config)

    async def start(self):
        """Start all enabled sinks."""
        start_tasks = []
        for name, sink in self.sinks.items():
            logger.info("Starting sink", sink=name)
            start_tasks.append(sink.start())

        if start_tasks:
            results = await asyncio.gather(*start_tasks, return_exceptions=True)
            
            # Check for exceptions in sink startup
            for i, result in enumerate(results):
                sink_name = list(self.sinks.keys())[i]
                if isinstance(result, Exception):
                    logger.error("Failed to start sink", sink=sink_name, error=str(result))
                    # Don't raise here, but log the failure for debugging
                else:
                    logger.info("Sink started successfully", sink=sink_name)

        logger.info("SinksManager started", enabled_sinks=list(self.sinks.keys()))

    async def stop(self):
        """Stop all sinks."""
        stop_tasks = []
        for name, sink in self.sinks.items():
            logger.info("Stopping sink", sink=name)
            stop_tasks.append(sink.stop())

        if stop_tasks:
            await asyncio.gather(*stop_tasks, return_exceptions=True)

        logger.info("SinksManager stopped")

    async def write_events(
        self, events: List[Dict[str, Any]]
    ) -> Dict[str, Dict[str, Any]]:
        """Write events to all enabled sinks and return per-sink stats."""
        if not events:
            return {}

        # Try direct writes first
        write_tasks = {}
        for name, sink in self.sinks.items():
            write_tasks[name] = asyncio.create_task(
                self._safe_write(name, sink, events)
            )

        # Wait for all writes to complete
        results = {}

        for name, task in write_tasks.items():
            try:
                result = await task
                results[name] = result

            except Exception as e:
                logger.error("Sink write failed", sink=name, error=str(e))
                results[name] = {
                    "written": 0,
                    "errors": len(events),
                    "retries": 0,
                    "queued": 0,
                }

        # Log summary with enhanced stats
        total_written = sum(result.get("written", 0) for result in results.values())
        total_errors = sum(result.get("errors", 0) for result in results.values())
        total_retries = sum(result.get("retries", 0) for result in results.values())
        total_queued = sum(result.get("queued", 0) for result in results.values())

        logger.info(
            "Multi-sink write completed",
            events=len(events),
            total_written=total_written,
            total_errors=total_errors,
            total_retries=total_retries,
            total_queued=total_queued,
            sink_results=results,
        )

        return results

    async def _safe_write(
        self, name: str, sink: ResilientSink, events: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Safely write to a sink with error handling and metrics observation."""
        with mship_sink_write_seconds.labels(sink=name).time():
            try:
                result = await sink.write_events(events)
                return result
            except Exception as e:
                logger.error("Sink write error", sink=name, error=str(e))
                return {"written": 0, "errors": len(events)}

    def get_health_status(self) -> Dict[str, Any]:
        """Get health status of all sinks."""
        sink_health = {}
        overall_healthy = True

        for name, sink in self.sinks.items():
            is_healthy = sink.is_healthy()
            sink_health[name] = {
                "healthy": is_healthy,
                "enabled": True,
                "stats": sink.get_stats(),
            }
            if not is_healthy:
                overall_healthy = False

        return {
            "healthy": overall_healthy,
            "sinks": sink_health,
            "enabled_sinks": list(self.sinks.keys()),
        }

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics from all sinks."""
        stats = {
            "enabled_sinks": list(self.sinks.keys()),
            "sink_count": len(self.sinks),
        }

        return stats

    def get_sink_names(self) -> List[str]:
        """Get names of all configured sinks."""
        return list(self.sinks.keys())

    def get_sink(self, name: str) -> Optional[ResilientSink]:
        """Get a specific sink by name."""
        return self.sinks.get(name)
