"""Syslog server input for EdgeBot supporting RFC3164 and RFC5424."""

import asyncio
import re
import socket
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Tuple, Callable
import structlog

logger = structlog.get_logger(__name__)

# RFC3164 Pattern
RFC3164_PATTERN = re.compile(
    r"^<(?P<pri>\d{1,3})>"
    r"(?P<timestamp>(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\s+"
    r"(?P<hostname>\S+)\s+"
    r"(?P<tag>[\w\-\.]+)(?:\[(?P<pid>\d+)\])?:\s*"
    r"(?P<message>.*)"
)

# RFC5424 Pattern
RFC5424_PATTERN = re.compile(
    r"^<(?P<pri>\d{1,3})>"
    r"(?P<version>\d+)\s+"
    r"(?P<timestamp>\S+)\s+"
    r"(?P<hostname>\S+)\s+"
    r"(?P<appname>\S+)\s+"
    r"(?P<procid>\S+)\s+"
    r"(?P<msgid>\S+)\s+"
    r"(?P<structured_data>\[.*?\]|\-)\s*"
    r"(?P<message>.*)"
)

# Facility and Severity mappings
FACILITIES = {
    0: "kernel",
    1: "user",
    2: "mail",
    3: "daemon",
    4: "security",
    5: "syslogd",
    6: "lpr",
    7: "news",
    8: "uucp",
    9: "cron",
    10: "authpriv",
    11: "ftp",
    16: "local0",
    17: "local1",
    18: "local2",
    19: "local3",
    20: "local4",
    21: "local5",
    22: "local6",
    23: "local7",
}

SEVERITIES = {
    0: "emergency",
    1: "alert",
    2: "critical",
    3: "error",
    4: "warning",
    5: "notice",
    6: "info",
    7: "debug",
}


class SyslogParser:
    """Syslog message parser supporting RFC3164 and RFC5424."""

    @staticmethod
    def parse_priority(pri: int) -> Tuple[int, int, str, str]:
        """Parse priority value into facility and severity."""
        facility = pri // 8
        severity = pri % 8
        facility_name = FACILITIES.get(facility, f"unknown_{facility}")
        severity_name = SEVERITIES.get(severity, f"unknown_{severity}")
        return facility, severity, facility_name, severity_name

    @staticmethod
    def parse_message(raw_message: str, client_addr: Tuple[str, int]) -> Dict[str, Any]:
        """Parse a syslog message and return structured data."""
        message_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source_ip": client_addr[0],
            "source_port": client_addr[1],
            "raw_message": raw_message.strip(),
            "type": "syslog",
            "rfc_variant": None,
        }

        # Try RFC5424 first
        match = RFC5424_PATTERN.match(raw_message)
        if match:
            return SyslogParser._parse_rfc5424(match, message_data)

        # Try RFC3164
        match = RFC3164_PATTERN.match(raw_message)
        if match:
            return SyslogParser._parse_rfc3164(match, message_data)

        # If no pattern matches, treat as raw message
        message_data.update(
            {
                "rfc_variant": "unknown",
                "facility": "unknown",
                "severity": "unknown",
                "hostname": "unknown",
                "message": raw_message.strip(),
                "parse_error": "Could not match RFC3164 or RFC5424 format",
            }
        )

        return message_data

    @staticmethod
    def _parse_rfc3164(match: re.Match, message_data: Dict[str, Any]) -> Dict[str, Any]:
        """Parse RFC3164 format message."""
        groups = match.groupdict()
        pri = int(groups["pri"])
        facility, severity, facility_name, severity_name = SyslogParser.parse_priority(
            pri
        )

        message_data.update(
            {
                "rfc_variant": "rfc3164",
                "priority": pri,
                "facility": facility_name,
                "facility_code": facility,
                "severity": severity_name,
                "severity_code": severity,
                "timestamp_original": groups["timestamp"],
                "hostname": groups["hostname"],
                "tag": groups["tag"],
                "process_id": groups["pid"],
                "message": groups["message"],
            }
        )

        return message_data

    @staticmethod
    def _parse_rfc5424(match: re.Match, message_data: Dict[str, Any]) -> Dict[str, Any]:
        """Parse RFC5424 format message."""
        groups = match.groupdict()
        pri = int(groups["pri"])
        facility, severity, facility_name, severity_name = SyslogParser.parse_priority(
            pri
        )

        message_data.update(
            {
                "rfc_variant": "rfc5424",
                "priority": pri,
                "facility": facility_name,
                "facility_code": facility,
                "severity": severity_name,
                "severity_code": severity,
                "version": int(groups["version"]),
                "timestamp_original": groups["timestamp"],
                "hostname": groups["hostname"],
                "app_name": groups["appname"],
                "process_id": groups["procid"] if groups["procid"] != "-" else None,
                "message_id": groups["msgid"] if groups["msgid"] != "-" else None,
                "structured_data": (
                    groups["structured_data"]
                    if groups["structured_data"] != "-"
                    else None
                ),
                "message": groups["message"],
            }
        )

        return message_data


class SyslogUDPProtocol(asyncio.DatagramProtocol):
    """UDP protocol handler for syslog messages."""

    def __init__(self, message_callback: Callable, max_message_size: int = 8192):
        self.message_callback = message_callback
        self.max_message_size = max_message_size
        self.transport = None

    def connection_made(self, transport):
        self.transport = transport
        logger.info(
            "Syslog UDP server started", local_addr=transport.get_extra_info("sockname")
        )

    def datagram_received(self, data: bytes, addr: Tuple[str, int]):
        """Handle incoming UDP datagram."""
        try:
            if len(data) > self.max_message_size:
                logger.warning(
                    "Received oversized UDP message",
                    size=len(data),
                    max_size=self.max_message_size,
                    source=addr[0],
                )
                return

            message = data.decode("utf-8", errors="replace")
            parsed_message = SyslogParser.parse_message(message, addr)
            parsed_message["transport"] = "udp"

            # Submit to callback without blocking
            asyncio.create_task(self.message_callback(parsed_message))

        except Exception as e:
            logger.error(
                "Error processing UDP syslog message", error=str(e), source=addr[0]
            )

    def error_received(self, exc):
        logger.error("UDP transport error", error=str(exc))


class SyslogTCPHandler:
    """TCP connection handler for syslog messages."""

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        message_callback: Callable,
        max_message_size: int = 8192,
    ):
        self.reader = reader
        self.writer = writer
        self.message_callback = message_callback
        self.max_message_size = max_message_size
        self.client_addr = writer.get_extra_info("peername")

    async def handle_connection(self):
        """Handle TCP connection and process messages."""
        logger.info("New TCP syslog connection", client=self.client_addr[0])

        try:
            while True:
                # Read message (assuming newline-delimited)
                data = await self.reader.readline()
                if not data:
                    break  # Connection closed

                if len(data) > self.max_message_size:
                    logger.warning(
                        "Received oversized TCP message",
                        size=len(data),
                        max_size=self.max_message_size,
                        client=self.client_addr[0],
                    )
                    continue

                message = data.decode("utf-8", errors="replace").rstrip("\r\n")
                if message:
                    parsed_message = SyslogParser.parse_message(
                        message, self.client_addr
                    )
                    parsed_message["transport"] = "tcp"

                    # Submit to callback
                    await self.message_callback(parsed_message)

        except asyncio.CancelledError:
            logger.info("TCP syslog connection cancelled", client=self.client_addr[0])
        except Exception as e:
            logger.error(
                "Error in TCP syslog connection",
                error=str(e),
                client=self.client_addr[0],
            )
        finally:
            self.writer.close()
            await self.writer.wait_closed()
            logger.info("TCP syslog connection closed", client=self.client_addr[0])


class SyslogServer:
    """Async syslog server supporting both UDP and TCP."""

    def __init__(self, config: Dict[str, Any], message_callback: Callable):
        self.config = config
        self.message_callback = message_callback
        self.udp_transport = None
        self.tcp_server = None
        self.running = False

    async def start(self):
        """Start the syslog server."""
        if not self.config.get("enabled", False):
            logger.info("Syslog input disabled")
            return

        self.running = True
        bind_address = self.config.get("bind_address", "0.0.0.0")
        udp_port = self.config.get("udp_port", 5514)
        tcp_port = self.config.get("tcp_port", 5515)
        max_message_size = self.config.get("max_message_size", 8192)

        # Start UDP server
        loop = asyncio.get_running_loop()
        transport, protocol = await loop.create_datagram_endpoint(
            lambda: SyslogUDPProtocol(self.message_callback, max_message_size),
            local_addr=(bind_address, udp_port),
            reuse_port=True,
        )
        self.udp_transport = transport

        # Start TCP server
        self.tcp_server = await asyncio.start_server(
            self._handle_tcp_client, bind_address, tcp_port, reuse_port=True
        )

        logger.info(
            "Syslog server started",
            udp_port=udp_port,
            tcp_port=tcp_port,
            bind_address=bind_address,
        )

    async def _handle_tcp_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ):
        """Handle new TCP client connection."""
        max_message_size = self.config.get("max_message_size", 8192)
        handler = SyslogTCPHandler(
            reader, writer, self.message_callback, max_message_size
        )
        await handler.handle_connection()

    async def stop(self):
        """Stop the syslog server."""
        if not self.running:
            return

        self.running = False

        # Close UDP transport
        if self.udp_transport:
            self.udp_transport.close()

        # Close TCP server
        if self.tcp_server:
            self.tcp_server.close()
            await self.tcp_server.wait_closed()

        logger.info("Syslog server stopped")

    def is_running(self) -> bool:
        """Check if the server is running."""
        return self.running


# Factory function for creating syslog server
def create_syslog_server(
    config: Dict[str, Any], message_callback: Callable
) -> SyslogServer:
    """Create a syslog server instance."""
    return SyslogServer(config, message_callback)
