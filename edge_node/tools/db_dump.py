#!/usr/bin/env python3
"""Dump SQLite spool database contents for inspection."""

import sys
import os
import json
import argparse
import sqlite3
from typing import Any, Dict

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def dump_schema(db_path: str):
    """Dump database schema."""
    print("=== Database Schema ===")

    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            """
            SELECT name, type, sql 
            FROM sqlite_master 
            WHERE type IN ('table', 'index')
            ORDER BY type, name
        """
        )

        for name, obj_type, sql in cursor.fetchall():
            print(f"{obj_type.upper()}: {name}")
            if sql:
                print(f"  SQL: {sql}")
            print()


def dump_stats(db_path: str):
    """Dump database statistics."""
    print("=== Database Statistics ===")

    with sqlite3.connect(db_path) as conn:
        # Overall stats
        cursor = conn.execute("SELECT COUNT(*) FROM messages")
        total = cursor.fetchone()[0]
        print(f"Total messages: {total}")

        # Status breakdown
        cursor = conn.execute(
            """
            SELECT status, COUNT(*) as count 
            FROM messages 
            GROUP BY status
            ORDER BY count DESC
        """
        )

        print("\nBy status:")
        for status, count in cursor.fetchall():
            print(f"  {status}: {count}")

        # Time range
        cursor = conn.execute(
            """
            SELECT 
                MIN(timestamp) as first_message,
                MAX(timestamp) as last_message,
                MAX(timestamp) - MIN(timestamp) as timespan
            FROM messages
        """
        )

        row = cursor.fetchone()
        if row and row[0]:
            from datetime import datetime

            first = datetime.fromtimestamp(row[0])
            last = datetime.fromtimestamp(row[1])
            timespan = row[2]

            print(f"\nTime range:")
            print(f"  First message: {first}")
            print(f"  Last message: {last}")
            print(f"  Timespan: {timespan:.2f} seconds")
        print()


def dump_sample_messages(db_path: str, limit: int = 10, status: str = None):
    """Dump sample messages."""
    print(f"=== Sample Messages (limit={limit}) ===")

    query = "SELECT id, timestamp, message_data, status FROM messages"
    params = []

    if status:
        query += " WHERE status = ?"
        params.append(status)

    query += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)

    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(query, params)

        for row in cursor.fetchall():
            msg_id, timestamp, message_data, msg_status = row

            print(f"ID: {msg_id}, Status: {msg_status}")
            print(f"Timestamp: {timestamp}")

            try:
                message = json.loads(message_data)
                print(f"Message: {json.dumps(message, indent=2)}")
            except json.JSONDecodeError:
                print(f"Message (raw): {message_data}")

            print("-" * 60)


def cleanup_completed(db_path: str, older_than_seconds: int, dry_run: bool = False):
    """Clean up completed messages."""
    import time

    cutoff_time = time.time() - older_than_seconds

    print(f"=== Cleanup {'(DRY RUN)' if dry_run else ''} ===")
    print(f"Removing completed messages older than {older_than_seconds} seconds")
    print(f"Cutoff timestamp: {cutoff_time}")

    with sqlite3.connect(db_path) as conn:
        # Count what would be deleted
        cursor = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE status = 'completed' AND timestamp < ?",
            (cutoff_time,),
        )
        count_to_delete = cursor.fetchone()[0]

        print(f"Messages to delete: {count_to_delete}")

        if not dry_run and count_to_delete > 0:
            cursor = conn.execute(
                "DELETE FROM messages WHERE status = 'completed' AND timestamp < ?",
                (cutoff_time,),
            )
            deleted = cursor.rowcount
            conn.commit()
            print(f"Actually deleted: {deleted}")
        else:
            print("No deletion performed (dry run or no messages to delete)")


def main():
    """Main function."""
    parser = argparse.ArgumentParser(
        description="Dump EdgeBot SQLite spool database contents"
    )
    parser.add_argument(
        "db_path",
        nargs="?",
        default="/tmp/edgebot_buffer.db",
        help="Path to the SQLite database",
    )

    # What to dump
    parser.add_argument("--schema", action="store_true", help="Show database schema")
    parser.add_argument("--stats", action="store_true", help="Show database statistics")
    parser.add_argument(
        "--messages", type=int, default=0, help="Show sample messages (specify limit)"
    )
    parser.add_argument(
        "--status",
        choices=["pending", "completed", "failed"],
        help="Filter messages by status",
    )

    # Cleanup options
    parser.add_argument(
        "--cleanup",
        type=int,
        metavar="SECONDS",
        help="Clean up completed messages older than SECONDS",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be cleaned up without deleting",
    )

    # Default behavior
    parser.add_argument(
        "--all", action="store_true", help="Show schema, stats, and 10 sample messages"
    )

    args = parser.parse_args()

    if not os.path.exists(args.db_path):
        print(f"Error: Database file '{args.db_path}' not found", file=sys.stderr)
        sys.exit(1)

    print(f"Database: {args.db_path}")
    print()

    if args.all:
        args.schema = True
        args.stats = True
        args.messages = 10

    try:
        if args.schema:
            dump_schema(args.db_path)

        if args.stats:
            dump_stats(args.db_path)

        if args.messages > 0:
            dump_sample_messages(args.db_path, args.messages, args.status)

        if args.cleanup is not None:
            cleanup_completed(args.db_path, args.cleanup, args.dry_run)

        # If no specific options, show basic info
        if not any(
            [
                args.schema,
                args.stats,
                args.messages > 0,
                args.cleanup is not None,
                args.all,
            ]
        ):
            dump_stats(args.db_path)
            dump_sample_messages(args.db_path, 5)

    except Exception as e:
        print(f"Error accessing database: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
