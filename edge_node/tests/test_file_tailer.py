import asyncio
import os
import tempfile
import unittest
from pathlib import Path
import sys

# Add the app directory to the path
sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

try:
    from inputs.file_tailer import FileTailer

    FILETAILER_AVAILABLE = True
except Exception:
    FILETAILER_AVAILABLE = False


class TestFileTailer(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        if not FILETAILER_AVAILABLE:
            self.skipTest("FileTailer not available (branch not merged yet)")
        self.tmp = tempfile.NamedTemporaryFile(mode="w+", delete=False)
        self.tmp_path = self.tmp.name
        self.messages = []

        async def cb(msg):
            self.messages.append(msg)

        self.cb = cb
        self.cfg = {
            "enabled": True,
            "paths": [self.tmp_path],
            "globs": [],
            "from_beginning": True,
            "scan_interval": 1,
        }
        self.tailer = FileTailer(self.cfg, self.cb)

    async def asyncTearDown(self):
        if FILETAILER_AVAILABLE:
            await self.tailer.stop()
        try:
            os.unlink(self.tmp_path)
        except Exception:
            pass

    async def test_tail_basic_and_rotation(self):
        await self.tailer.start()
        # write some lines
        self.tmp.write("line1\n")
        self.tmp.flush()
        await asyncio.sleep(1.5)
        # Expect at least one message
        self.assertTrue(any(m.get("message") == "line1" for m in self.messages))

        # Test that we can add more lines to the same file
        self.tmp.write("line3\n")
        self.tmp.flush()
        await asyncio.sleep(1.5)
        self.assertTrue(any(m.get("message") == "line3" for m in self.messages))
