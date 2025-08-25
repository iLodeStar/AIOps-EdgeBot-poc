import asyncio
import os
import subprocess
import tempfile
import unittest
from unittest import mock
from pathlib import Path
import sys

# Add the app directory to the path
sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

try:
    from inputs.service_discovery import ServiceDiscovery
    from inputs.file_tailer import FileTailer

    DISCOVERY_AVAILABLE = True
except Exception:
    DISCOVERY_AVAILABLE = False


class TestServiceDiscovery(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        if not DISCOVERY_AVAILABLE:
            self.skipTest(
                "ServiceDiscovery/FileTailer not available (branch not merged yet)"
            )
        self.messages = []

        async def cb(msg):
            self.messages.append(msg)

        self.cb = cb
        # temp log file to be "discovered"
        self.tmp = tempfile.NamedTemporaryFile(mode="w+", delete=False)
        self.tmp_path = self.tmp.name

        self.tailer = FileTailer({"enabled": True, "paths": [], "globs": []}, self.cb)
        await self.tailer.start()
        self.discovery = ServiceDiscovery(
            {
                "enabled": True,
                "interval": 1,
                "auto_tail_logs": True,
                "extra_logs": [self.tmp_path],
            },
            self.cb,
            tailer=self.tailer,
        )

    async def asyncTearDown(self):
        if DISCOVERY_AVAILABLE:
            await self.discovery.stop()
            await self.tailer.stop()
        try:
            os.unlink(self.tmp_path)
        except Exception:
            pass

    @mock.patch.object(subprocess, "check_output")
    async def test_discover_once(self, mock_ss):
        # Minimal fake 'ss' output with header + one line
        mock_ss.return_value = (
            "Netid State  Recv-Q Send-Q Local Address:Port  Peer Address:Port Process\n"
            'udp   UNCONN 0      0      0.0.0.0:5514       0.0.0.0:*     users:("python",pid=123,fd=5)\n'
        )
        # invoke one iteration
        await self.discovery._discover_once()
        # Should have sent an inventory message
        self.assertTrue(
            any(m.get("type") == "host_service_inventory" for m in self.messages)
        )
        # Tailer should have registered our extra log
        self.assertIn(self.tmp_path, self.tailer.paths)
