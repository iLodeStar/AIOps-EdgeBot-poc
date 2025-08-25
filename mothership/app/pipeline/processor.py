"""Base processor classes and pipeline runner."""

import asyncio
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Union
import structlog
import time

logger = structlog.get_logger()


class Processor(ABC):
    """Base class for all data processors."""

    def __init__(self, config: Dict[str, Any], name: str = None):
        self.config = config
        self.name = name or self.__class__.__name__
        self.stats = {"processed": 0, "errors": 0, "total_time": 0.0}

    @abstractmethod
    async def process(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Process a single event and return the modified event."""
        pass

    async def process_batch(self, events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Process a batch of events. Default implementation processes one by one."""
        results = []
        for event in events:
            try:
                start_time = time.time()
                result = await self.process(event)
                self.stats["processed"] += 1
                self.stats["total_time"] += time.time() - start_time
                results.append(result)
            except Exception as e:
                self.stats["errors"] += 1
                logger.error(
                    f"Error in processor {self.name}",
                    error=str(e),
                    event_id=event.get("id"),
                )
                # Return original event on error (fail-safe)
                results.append(event)
        return results

    def get_stats(self) -> Dict[str, Any]:
        """Get processor statistics."""
        stats = self.stats.copy()
        if stats["processed"] > 0:
            stats["avg_processing_time"] = stats["total_time"] / stats["processed"]
        else:
            stats["avg_processing_time"] = 0.0
        return stats

    def is_enabled(self) -> bool:
        """Check if processor is enabled in config."""
        return self.config.get("enabled", True)


class Pipeline:
    """Pipeline runner that orchestrates multiple processors."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.processors: List[Processor] = []
        self.stats = {
            "total_events": 0,
            "successful_events": 0,
            "failed_events": 0,
            "total_time": 0.0,
        }

    def add_processor(self, processor: Processor):
        """Add a processor to the pipeline."""
        if processor.is_enabled():
            self.processors.append(processor)
            logger.info(f"Added processor to pipeline", processor=processor.name)
        else:
            logger.info(f"Processor disabled, skipping", processor=processor.name)

    async def process_events(
        self, events: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Process a batch of events through the pipeline."""
        if not events:
            return []

        start_time = time.time()
        current_events = events.copy()

        try:
            # Process through each processor in order
            for processor in self.processors:
                logger.debug(
                    f"Processing batch through {processor.name}",
                    events=len(current_events),
                )
                current_events = await processor.process_batch(current_events)

            # Update statistics
            self.stats["total_events"] += len(events)
            self.stats["successful_events"] += len(current_events)
            self.stats["total_time"] += time.time() - start_time

            logger.info(
                "Pipeline processing completed",
                input_events=len(events),
                output_events=len(current_events),
            )

            return current_events

        except Exception as e:
            self.stats["failed_events"] += len(events)
            logger.error("Pipeline processing failed", error=str(e))
            raise

    async def process_single_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Process a single event through the pipeline."""
        results = await self.process_events([event])
        return results[0] if results else event

    def get_stats(self) -> Dict[str, Any]:
        """Get pipeline statistics including processor stats."""
        stats = self.stats.copy()
        stats["processors"] = {}

        for processor in self.processors:
            stats["processors"][processor.name] = processor.get_stats()

        if stats["total_events"] > 0:
            stats["avg_processing_time"] = stats["total_time"] / stats["total_events"]
            stats["success_rate"] = stats["successful_events"] / stats["total_events"]
        else:
            stats["avg_processing_time"] = 0.0
            stats["success_rate"] = 0.0

        return stats

    def get_enabled_processors(self) -> List[str]:
        """Get list of enabled processor names."""
        return [p.name for p in self.processors]


class ProcessingContext:
    """Context object passed through the pipeline for sharing state."""

    def __init__(self, pipeline_id: str = None):
        self.pipeline_id = pipeline_id or f"pipeline_{int(time.time() * 1000)}"
        self.metadata = {}
        self.audit_log = []
        self.start_time = time.time()

    def add_audit_entry(
        self, processor_name: str, action: str, details: Dict[str, Any] = None
    ):
        """Add an entry to the audit log."""
        entry = {
            "processor": processor_name,
            "action": action,
            "timestamp": time.time(),
            "details": details or {},
        }
        self.audit_log.append(entry)

    def get_processing_time(self) -> float:
        """Get total processing time so far."""
        return time.time() - self.start_time

    def to_dict(self) -> Dict[str, Any]:
        """Convert context to dictionary for logging/storage."""
        return {
            "pipeline_id": self.pipeline_id,
            "metadata": self.metadata,
            "audit_log": self.audit_log,
            "processing_time": self.get_processing_time(),
            "start_time": self.start_time,
        }
