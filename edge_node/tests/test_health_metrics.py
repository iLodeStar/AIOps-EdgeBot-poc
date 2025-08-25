import unittest
from pathlib import Path
import sys

# Add the app directory to the path
sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

try:
    from main import HealthServer

    HEALTH_AVAILABLE = True
except Exception:
    HEALTH_AVAILABLE = False


class DummyService:
    def __init__(self, running=True):
        self._running = running

    def is_running(self):
        return self._running

    def get_status(self):
        return {"running": self._running, "sample": 1}


class TestHealthMetrics(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        if not HEALTH_AVAILABLE:
            self.skipTest("HealthServer not importable (aiohttp missing?)")
        self.services = {"dummy": DummyService()}
        self.server = HealthServer(
            {
                "observability": {
                    "health_port": 0,
                    "metrics_path": "/metrics",
                    "health_path": "/healthz",
                },
                "server": {"host": "127.0.0.1", "port": 0},
            },
            self.services,
        )

    async def asyncTearDown(self):
        if HEALTH_AVAILABLE:
            await self.server.stop()

    async def test_start(self):
        await self.server.start()
        # Ensure services registered; actual HTTP calls are not required for this smoke test
        self.assertIn("dummy", self.server.services)
