"""Network flow telemetry listener for NetFlow v5/v9/IPFIX and sFlow.

Phase 1: detect protocol/version, record packet sizes and counts, and forward raw payload as base64
with basic metadata for visibility.
"""
import asyncio
import base64
from typing import Dict, Any, Callable, Optional, Tuple
import structlog

logger = structlog.get_logger(__name__)


class FlowsListener:
    def __init__(self, config: Dict[str, Any], message_callback: Callable):
        self.config = config
        self.message_callback = message_callback
        self.running = False
        self.tasks = []

    async def start(self):
        if not self.config.get('enabled', False):
            logger.info("Flows listener disabled")
            return
        self.running = True
        # Start UDP servers for configured ports
        for port in self.config.get('netflow_ports', []):
            self.tasks.append(asyncio.create_task(self._udp_server(port, 'netflow')))
        for port in self.config.get('ipfix_ports', []):
            self.tasks.append(asyncio.create_task(self._udp_server(port, 'ipfix')))
        for port in self.config.get('sflow_ports', []):
            self.tasks.append(asyncio.create_task(self._udp_server(port, 'sflow')))
        logger.info("Flows listener started",
                    netflow=len(self.config.get('netflow_ports', [])),
                    ipfix=len(self.config.get('ipfix_ports', [])),
                    sflow=len(self.config.get('sflow_ports', [])))

    async def stop(self):
        self.running = False
        for t in self.tasks:
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass
        self.tasks.clear()
        logger.info("Flows listener stopped")

    def is_running(self) -> bool:
        return self.running

    def get_status(self) -> Dict[str, Any]:
        return {
            'enabled': self.config.get('enabled', False),
            'running': self.running,
            'netflow_ports': self.config.get('netflow_ports', []),
            'ipfix_ports': self.config.get('ipfix_ports', []),
            'sflow_ports': self.config.get('sflow_ports', []),
        }

    async def _udp_server(self, port: int, kind: str):
        loop = asyncio.get_running_loop()
        transport, protocol = await loop.create_datagram_endpoint(
            lambda: _FlowUDPProtocol(self.message_callback, kind),
            local_addr=('0.0.0.0', port),
            reuse_port=True
        )
        logger.info("Flow UDP server started", kind=kind, port=port)
        try:
            while self.running:
                await asyncio.sleep(3600)
        finally:
            transport.close()


class _FlowUDPProtocol(asyncio.DatagramProtocol):
    def __init__(self, cb: Callable, kind: str):
        self.cb = cb
        self.kind = kind

    def datagram_received(self, data: bytes, addr: Tuple[str, int]):
        version = self._detect_version(data)
        payload_b64 = base64.b64encode(data).decode('ascii')
        msg = {
            'type': 'flow_packet',
            'subtype': self.kind,
            'version': version,
            'source_ip': addr[0],
            'source_port': addr[1],
            'size_bytes': len(data),
            'payload_b64': payload_b64,
        }
        asyncio.create_task(self.cb(msg))

    def error_received(self, exc):
        logger.warning("Flow UDP error", error=str(exc))

    @staticmethod
    def _detect_version(data: bytes) -> Optional[int]:
        if len(data) < 2:
            return None
        # NetFlow v5/v9 and IPFIX have first 2 bytes as version
        v = int.from_bytes(data[0:2], 'big')
        # sFlow datagrams start with 32-bit version 5
        if v in (5, 9, 10):
            return v
        if len(data) >= 4:
            v32 = int.from_bytes(data[0:4], 'big')
            if v32 == 5:
                return 5
        return None