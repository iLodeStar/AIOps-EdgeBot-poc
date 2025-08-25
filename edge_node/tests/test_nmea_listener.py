import asyncio
import socket
import unittest
from pathlib import Path
import sys

# Add the app directory to the path
sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

try:
    from inputs.nmea_listener import NMEAListener

    NMEA_AVAILABLE = True
except Exception:
    NMEA_AVAILABLE = False


class TestNMEAListener(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        if not NMEA_AVAILABLE:
            self.skipTest("NMEAListener not available (branch not merged yet)")
        self.messages = []

        async def cb(msg):
            self.messages.append(msg)

        self.cb = cb
        self.port = self._free_udp_port()
        self.listener = NMEAListener(
            {
                "enabled": True,
                "mode": "udp",
                "bind_address": "127.0.0.1",
                "udp_port": self.port,
            },
            self.cb,
        )

    async def asyncTearDown(self):
        if NMEA_AVAILABLE:
            await self.listener.stop()

    def _free_udp_port(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        return port

    async def test_parse_gprmc(self):
        await self.listener.start()
        await asyncio.sleep(0.2)

        line = b"$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,,*6A\r\n"
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.sendto(line, ("127.0.0.1", self.port))
        sock.close()

        await asyncio.sleep(0.5)
        self.assertTrue(self.messages)
        msg = self.messages[0]
        self.assertEqual(msg.get("type"), "nmea")
        self.assertEqual(msg.get("sentence")[-3:], "RMC")
        self.assertIn("lat", msg)
        self.assertIn("lon", msg)
