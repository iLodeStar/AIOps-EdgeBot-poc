"""File tailer input for EdgeBot.

- Tails multiple files (explicit paths and glob patterns)
- Handles rotations (inode change) and truncation
- Emits one message per line with file metadata
"""

import asyncio
import os
import glob
import time
from typing import Dict, Any, Callable, List, Optional, Tuple

import structlog

logger = structlog.get_logger(__name__)


class _TailState:
    def __init__(self, path: str, fh, inode: int, position: int):
        self.path = path
        self.fh = fh
        self.inode = inode
        self.position = position


class FileTailer:
    def __init__(self, config: Dict[str, Any], message_callback: Callable):
        self.config = config
        self.message_callback = message_callback
        self.running = False
        self.scan_interval = int(config.get("scan_interval", 2))
        self.read_chunk = int(config.get("read_chunk", 8192))
        self.from_beginning = bool(config.get("from_beginning", False))
        self.paths: List[str] = list(config.get("paths", []))
        self.globs: List[str] = list(config.get("globs", []))
        self._tail_states: Dict[str, _TailState] = {}
        self._task: Optional[asyncio.Task] = None

    def add_path(self, path: str):
        if path not in self.paths:
            self.paths.append(path)
            logger.info("FileTailer: added path", path=path)

    async def start(self):
        if not self.config.get("enabled", False):
            logger.info("FileTailer disabled")
            return
        self.running = True
        self._task = asyncio.create_task(self._run())
        logger.info("FileTailer started", paths=len(self.paths), globs=len(self.globs))

    async def stop(self):
        self.running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        # Close open file handles
        for st in self._tail_states.values():
            try:
                st.fh.close()
            except Exception:
                pass
        self._tail_states.clear()
        logger.info("FileTailer stopped")

    def is_running(self) -> bool:
        return self.running

    def get_status(self) -> Dict[str, Any]:
        return {
            "enabled": self.config.get("enabled", False),
            "running": self.running,
            "files_tailed": len(self._tail_states),
            "paths": self.paths,
            "globs": self.globs,
        }

    async def _run(self):
        # Initial registration of files
        await self._refresh_file_set()
        if not self.from_beginning:
            # Seek to end initially
            for st in self._tail_states.values():
                st.fh.seek(0, os.SEEK_END)
                st.position = st.fh.tell()
        while self.running:
            try:
                await self._refresh_file_set()
                await self._read_new_lines()
                await asyncio.sleep(self.scan_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("FileTailer loop error", error=str(e))
                await asyncio.sleep(5)

    async def _refresh_file_set(self):
        active_paths = set(self.paths)
        for pattern in self.globs:
            try:
                for p in glob.glob(pattern):
                    active_paths.add(p)
            except Exception as e:
                logger.warning("Glob error", pattern=pattern, error=str(e))

        # Open any new files
        for p in active_paths:
            if p in self._tail_states:
                continue
            try:
                fh = open(p, "r", encoding="utf-8", errors="replace")
                inode = os.fstat(fh.fileno()).st_ino
                self._tail_states[p] = _TailState(p, fh, inode, 0)
                logger.info("Tailing file", path=p)
            except Exception as e:
                logger.debug("Cannot open file to tail", path=p, error=str(e))

        # Detect rotation or removal
        to_remove = []
        for p, st in self._tail_states.items():
            try:
                stat = os.stat(p)
                if stat.st_ino != st.inode or stat.st_size < st.position:
                    # Rotated or truncated
                    try:
                        st.fh.close()
                    except Exception:
                        pass
                    fh = open(p, "r", encoding="utf-8", errors="replace")
                    self._tail_states[p] = _TailState(
                        p, fh, os.fstat(fh.fileno()).st_ino, 0
                    )
                    logger.info("Reopened rotated file", path=p)
            except FileNotFoundError:
                to_remove.append(p)
            except Exception as e:
                logger.debug("Stat error", path=p, error=str(e))
        for p in to_remove:
            st = self._tail_states.pop(p, None)
            if st and st.fh:
                try:
                    st.fh.close()
                except Exception:
                    pass
            logger.info("Stopped tailing missing file", path=p)

    async def _read_new_lines(self):
        for p, st in list(self._tail_states.items()):
            try:
                st.fh.seek(st.position)
                while True:
                    line = st.fh.readline()
                    if not line:
                        break
                    st.position = st.fh.tell()
                    line = line.rstrip("\n")
                    if not line:
                        continue
                    msg = {
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "type": "log",
                        "file_path": p,
                        "message": line,
                    }
                    # Best-effort service labeling for common paths
                    if "/nginx/" in p or p.endswith("access.log"):
                        msg["service"] = "web"
                    elif "dns" in p or "unbound" in p or "bind" in p:
                        msg["service"] = "dns"
                    await self.message_callback(msg)
            except Exception as e:
                logger.debug("Tail read error", path=p, error=str(e))
