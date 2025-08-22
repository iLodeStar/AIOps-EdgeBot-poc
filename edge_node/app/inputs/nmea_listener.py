"""NMEA 0183 listener for vessel telemetry.

Supports UDP/TCP line-based input; parses common sentences and emits normalized messages.
"""
import asyncio
import re
from typing import Dict, Any, Callable, Optional, Tuple
import structlog

logger = structlog.get_logger(__name__)

# Simple regex for NMEA lines (no checksum validation for phase 1)
NMEA_RE = re.compile(r'^\$(?P<sentence>[A-Z]{2}[A-Z0-9]{3}),(.+?)\*(?P<cs>[0-9A-F]{2})')


class NMEAListener:
    def __init__(self, config: Dict[str, Any], message_callback: Callable):
        self.config = config
        self.message_callback = message_callback
        self.running = False
        self.udp_task: Optional[asyncio.Task] = None
        self.tcp_server = None

    async def start(self):
        if not self.config.get('enabled', False):
            logger.info("NMEA listener disabled")
            return
        self.running = True
        mode = self.config.get('mode', 'udp')
        bind = self.config.get('bind_address', '0.0.0.0')
        if mode == 'udp':
            port = int(self.config.get('udp_port', 10110))
            loop = asyncio.get_running_loop()
            await loop.create_datagram_endpoint(lambda: _NMEAUDP(self._handle_line), local_addr=(bind, port), reuse_port=True)
            logger.info("NMEA UDP listener started", port=port)
        elif mode == 'tcp':
            port = int(self.config.get('tcp_port', 10110))
            self.tcp_server = await asyncio.start_server(self._handle_tcp_client, bind, port)
            logger.info("NMEA TCP listener started", port=port)
        else:
            logger.warning("NMEA serial mode not implemented in container; use UDP/TCP")

    async def stop(self):
        self.running = False
        if self.tcp_server:
            self.tcp_server.close()
            await self.tcp_server.wait_closed()
        logger.info("NMEA listener stopped")

    def is_running(self) -> bool:
        return self.running

    def get_status(self) -> Dict[str, Any]:
        return {
            'enabled': self.config.get('enabled', False),
            'running': self.running,
            'mode': self.config.get('mode', 'udp'),
        }

    async def _handle_tcp_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        addr = writer.get_extra_info('peername')
        logger.info("NMEA TCP connection", client=addr)
        try:
            while True:
                data = await reader.readline()
                if not data:
                    break
                line = data.decode('ascii', errors='ignore').strip()
                if line:
                    await self._handle_line(line)
        finally:
            writer.close()
            await writer.wait_closed()

    async def _handle_line(self, line: str):
        m = NMEA_RE.match(line)
        if not m:
            return
        sentence = m.group('sentence')
        fields = line.split(',')
        ts = None
        msg: Dict[str, Any] = {'type': 'nmea', 'sentence': sentence, 'raw': line}
        try:
            if sentence.endswith('RMC') and len(fields) >= 12:
                # $GPRMC,hhmmss.sss,A,lat,NS,lon,EW,sog,cog,ddmmyy,...
                status = fields[2]
                lat = _nmea_to_deg(fields[3], fields[4])
                lon = _nmea_to_deg(fields[5], fields[6])
                sog = _to_float(fields[7])  # knots
                cog = _to_float(fields[8])  # degrees
                msg.update({'valid': status == 'A', 'lat': lat, 'lon': lon, 'sog_kn': sog, 'cog_deg': cog})
            elif sentence.endswith('VTG') and len(fields) >= 9:
                cog = _to_float(fields[1])
                sog = _to_float(fields[5])  # knots
                msg.update({'cog_deg': cog, 'sog_kn': sog})
            elif sentence.endswith('HDT') and len(fields) >= 2:
                hdg = _to_float(fields[1])
                msg.update({'heading_true_deg': hdg})
        finally:
            await self.message_callback(msg)


class _NMEAUDP(asyncio.DatagramProtocol):
    def __init__(self, cb: Callable[[str], Any]):
        self.cb = cb

    def datagram_received(self, data: bytes, addr: Tuple[str, int]):
        try:
            line = data.decode('ascii', errors='ignore').strip()
            if line:
                asyncio.create_task(self.cb(line))
        except Exception:
            pass


def _nmea_to_deg(val: str, hemi: str) -> Optional[float]:
    try:
        if not val:
            return None
        # ddmm.mmmm -> degrees
        if len(val) < 3:
            return None
        dlen = 2 if hemi in ('N', 'S') else 3
        deg = float(val[:dlen])
        minutes = float(val[dlen:])
        res = deg + minutes / 60.0
        if hemi in ('S', 'W'):
            res = -res
        return res
    except Exception:
        return None


def _to_float(s: str) -> Optional[float]:
    try:
        return float(s) if s else None
    except Exception:
        return None