import asyncio
import socket
import unittest
from pathlib import Path
import sys

# Add the app directory to the path
sys.path.insert(0, str(Path(__file__).parent.parent / 'app'))

try:
    from inputs.flows_listener import FlowsListener
    FLOWS_AVAILABLE = True
except Exception:
    FLOWS_AVAILABLE = False


class TestFlowsListener(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        if not FLOWS_AVAILABLE:
            self.skipTest("FlowsListener not available (branch not merged yet)")
        self.messages = []

        async def cb(msg):
            self.messages.append(msg)

        self.cb = cb
        self.port = self._free_udp_port()
        self.listener = FlowsListener(
            {"enabled": True, "netflow_ports": [self.port], "ipfix_ports": [], "sflow_ports": []},
            self.cb,
        )

    async def asyncTearDown(self):
        if FLOWS_AVAILABLE:
            await self.listener.stop()

    def _free_udp_port(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        return port

    async def test_receive_netflow_v5(self):
        await self.listener.start()
        await asyncio.sleep(0.2)

        # Send NetFlow v5-like packet (first two bytes = 0x0005)
        data = b"\x00\x05" + b"\x00" * 46
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.sendto(data, ("127.0.0.1", self.port))
        sock.close()

        # allow async callback to fire
        await asyncio.sleep(0.5)
        self.assertTrue(self.messages)
        msg = self.messages[0]
        self.assertEqual(msg.get("type"), "flow_packet")
        self.assertEqual(msg.get("subtype"), "netflow")
        self.assertIn("payload_b64", msg)
        self.assertIn("size_bytes", msg)