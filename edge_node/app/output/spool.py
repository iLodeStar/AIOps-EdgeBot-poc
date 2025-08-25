"""SQLite-backed message spool for persistent buffering."""

import sqlite3
import json
import time
import threading
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
import structlog

logger = structlog.get_logger(__name__)


class SQLiteSpool:
    """SQLite-backed message spool with transaction support."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        """Initialize the SQLite database and tables."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    message_data TEXT NOT NULL,
                    status TEXT DEFAULT 'pending'
                )
            """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_status_timestamp 
                ON messages(status, timestamp)
            """
            )
            conn.commit()

    def put(self, message: Dict[str, Any]) -> int:
        """Add a message to the spool and return its ID."""
        with self._lock:
            # Add spool ID and timestamp
            spool_message = message.copy()
            spool_message["__spool_timestamp"] = time.time()

            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    "INSERT INTO messages (timestamp, message_data) VALUES (?, ?)",
                    (time.time(), json.dumps(spool_message)),
                )
                message_id = cursor.lastrowid
                conn.commit()

                # Add the spool ID to the message for tracking
                spool_message["__spool_id"] = message_id
                conn.execute(
                    "UPDATE messages SET message_data = ? WHERE id = ?",
                    (json.dumps(spool_message), message_id),
                )
                conn.commit()

                return message_id

    def get_batch(self, batch_size: int) -> List[Dict[str, Any]]:
        """Get a batch of pending messages."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    "SELECT id, message_data FROM messages WHERE status = 'pending' ORDER BY timestamp LIMIT ?",
                    (batch_size,),
                )
                rows = cursor.fetchall()

                messages = []
                for row_id, message_data in rows:
                    try:
                        message = json.loads(message_data)
                        messages.append(message)
                    except json.JSONDecodeError as e:
                        logger.error(
                            "Failed to decode message", id=row_id, error=str(e)
                        )
                        # Mark as failed to avoid reprocessing
                        conn.execute(
                            "UPDATE messages SET status = 'failed' WHERE id = ?",
                            (row_id,),
                        )

                conn.commit()
                return messages

    def commit_batch(self, messages: List[Dict[str, Any]], success: bool):
        """Commit or rollback a batch of messages."""
        if not messages:
            return

        with self._lock:
            message_ids = []
            for message in messages:
                if "__spool_id" in message:
                    message_ids.append(message["__spool_id"])

            if not message_ids:
                return

            status = "completed" if success else "failed"
            placeholders = ",".join("?" * len(message_ids))

            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    f"UPDATE messages SET status = ? WHERE id IN ({placeholders})",
                    [status] + message_ids,
                )
                conn.commit()

                logger.debug(
                    "Batch committed",
                    status=status,
                    message_ids=message_ids,
                    count=len(message_ids),
                )

    def size(self) -> int:
        """Get the number of pending messages."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE status = 'pending'"
            )
            return cursor.fetchone()[0]

    def get_stats(self) -> Dict[str, Any]:
        """Get spool statistics."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT status, COUNT(*) as count 
                FROM messages 
                GROUP BY status
            """
            )
            status_counts = dict(cursor.fetchall())

            cursor = conn.execute("SELECT COUNT(*) FROM messages")
            total_messages = cursor.fetchone()[0]

            return {
                "total_messages": total_messages,
                "pending": status_counts.get("pending", 0),
                "completed": status_counts.get("completed", 0),
                "failed": status_counts.get("failed", 0),
                "db_path": self.db_path,
            }

    def cleanup_completed(self, older_than_seconds: int = 86400):
        """Remove completed messages older than specified seconds."""
        cutoff_time = time.time() - older_than_seconds

        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    "DELETE FROM messages WHERE status = 'completed' AND timestamp < ?",
                    (cutoff_time,),
                )
                deleted = cursor.rowcount
                conn.commit()

                if deleted > 0:
                    logger.info(
                        "Cleaned up completed messages",
                        deleted=deleted,
                        older_than_seconds=older_than_seconds,
                    )

                return deleted
