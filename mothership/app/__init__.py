"""Mothership data processing and ingestion service with dual-sink support."""

from .config import ConfigManager
from .server import app

__all__ = ["ConfigManager", "app"]
