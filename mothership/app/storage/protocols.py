"""Protocol definitions for storage sinks."""

from typing import Dict, Any, List, Protocol


class StorageSink(Protocol):
    """Protocol for storage sinks."""

    async def start(self) -> None:
        """Start the sink."""
        ...

    async def stop(self) -> None:
        """Stop the sink."""
        ...

    async def write_events(self, events: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Write events and return stats."""
        ...

    def is_healthy(self) -> bool:
        """Check if sink is healthy."""
        ...
