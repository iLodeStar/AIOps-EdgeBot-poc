"""Service discovery for EdgeBot.

- Enumerates listening ports via `ss -tulpn` (if available)
- Checks for common log file locations (nginx, bind, unbound, dnsmasq, captive portal)
- Emits inventory messages and can register discovered files with FileTailer
"""

import asyncio
import os
import shlex
import subprocess
from typing import Dict, Any, Callable, List, Optional
import structlog

logger = structlog.get_logger(__name__)

COMMON_LOGS = [
    "/var/log/nginx/access.log",
    "/var/log/nginx/error.log",
    "/var/log/dnsmasq.log",
    "/var/log/unbound/unbound.log",
    "/var/log/bind/bind.log",
    "/var/log/httpd/access_log",
    "/var/log/httpd/error_log",
]


class ServiceDiscovery:
    def __init__(self, config: Dict[str, Any], message_callback: Callable, tailer=None):
        self.config = config
        self.message_callback = message_callback
        self.tailer = tailer  # optional reference to FileTailer for auto-registration
        self.running = False
        self.task: Optional[asyncio.Task] = None
        self.interval = int(config.get("interval", 300))

    async def start(self):
        if not self.config.get("enabled", False):
            logger.info("Service discovery disabled")
            return
        self.running = True
        self.task = asyncio.create_task(self._run())
        logger.info("Service discovery started", interval=self.interval)

    async def stop(self):
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        logger.info("Service discovery stopped")

    def is_running(self) -> bool:
        return self.running

    def get_status(self) -> Dict[str, Any]:
        return {
            "enabled": self.config.get("enabled", False),
            "running": self.running,
            "interval": self.interval,
        }

    async def _run(self):
        while self.running:
            try:
                await self._discover_once()
                await asyncio.sleep(self.interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Discovery loop error", error=str(e))
                await asyncio.sleep(60)

    async def _discover_once(self):
        services = self._discover_listeners()
        logs = self._discover_logs()
        msg = {
            "type": "host_service_inventory",
            "listeners": services,
            "log_candidates": logs,
        }
        await self.message_callback(msg)
        if self.tailer and self.config.get("auto_tail_logs", True):
            for p in logs:
                self.tailer.add_path(p)

    def _discover_listeners(self) -> List[Dict[str, Any]]:
        try:
            cmd = shlex.split("ss -tulpn")
            out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)
            lines = out.splitlines()[1:]
            results = []
            for ln in lines:
                # proto state recv-q send-q local:port peer:port users:(("proc",pid=...))
                parts = ln.split()
                if len(parts) < 5:
                    continue
                proto = parts[0]
                local = parts[4]
                proc = parts[-1] if parts[-1].startswith("users:") else None
                results.append({"proto": proto, "local": local, "proc": proc})
            return results
        except Exception as e:
            logger.debug("ss not available", error=str(e))
            return []

    def _discover_logs(self) -> List[str]:
        found = []
        for p in COMMON_LOGS + self.config.get("extra_logs", []):
            try:
                if os.path.isfile(p) and os.access(p, os.R_OK):
                    found.append(p)
            except Exception:
                pass
        return found
