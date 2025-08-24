"""Async TimescaleDB writer using psycopg3."""

import asyncio
import json
import time
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
import psycopg
from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
import structlog

logger = structlog.get_logger()


class TimescaleDBWriter:
    """Async TimescaleDB writer with connection pooling and batch inserts."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.pool: Optional[AsyncConnectionPool] = None

        # Connection configuration
        self.dsn = self._build_dsn()
        self.pool_min_size = config.get("pool_min_size", 5)
        self.pool_max_size = config.get("pool_max_size", 20)
        self.connection_timeout = config.get("connection_timeout", 30)

        # Table configuration
        self.table_name = config.get("table_name", "events")
        self.hypertable_chunk_interval = config.get("chunk_interval", "1 day")

        # Batch configuration
        self.batch_size = config.get("batch_size", 1000)
        self.batch_timeout = config.get("batch_timeout", 5.0)

        # Statistics
        self.stats = {
            "total_inserts": 0,
            "total_batches": 0,
            "total_errors": 0,
            "last_insert_time": None,
            "last_error_time": None,
        }

        logger.info(
            "Initialized TimescaleDB writer",
            dsn=self._safe_dsn(),
            table=self.table_name,
            pool_size=f"{self.pool_min_size}-{self.pool_max_size}",
        )

    def _build_dsn(self) -> str:
        """Build database connection string."""
        if "dsn" in self.config:
            return self.config["dsn"]

        # Build from individual components
        host = self.config.get("host", "localhost")
        port = self.config.get("port", 5432)
        database = self.config.get("database", "mothership")
        user = self.config.get("user", "mothership")
        password = self.config.get("password", "")

        return f"postgresql://{user}:{password}@{host}:{port}/{database}"

    def _safe_dsn(self) -> str:
        """Return DSN with password masked."""
        dsn = self.dsn
        if ":" in dsn and "@" in dsn:
            parts = dsn.split("@")
            if len(parts) == 2:
                user_part = parts[0].split("://")[-1]
                if ":" in user_part:
                    user, _ = user_part.rsplit(":", 1)
                    return f"{dsn.split('://')[0]}://{user}:***@{parts[1]}"
        return dsn

    async def initialize(self):
        """Initialize connection pool and create tables if needed."""
        try:
            # Create connection pool
            self.pool = AsyncConnectionPool(
                self.dsn,
                min_size=self.pool_min_size,
                max_size=self.pool_max_size,
                open=False,
            )

            await self.pool.open()
            logger.info("Connection pool opened")

            # Create tables and indexes
            await self._create_tables()

        except Exception as e:
            logger.error("Failed to initialize TimescaleDB", error=str(e))
            raise

    async def close(self):
        """Close connection pool."""
        if self.pool:
            await self.pool.close()
            logger.info("Connection pool closed")

    async def _create_tables(self):
        """Create tables and indexes if they don't exist."""
        async with self.pool.connection() as conn:
            # Create events table
            await conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self.table_name} (
                    ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    type TEXT NOT NULL,
                    source TEXT NOT NULL,
                    data JSONB NOT NULL,
                    id BIGSERIAL,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """
            )

            # Create hypertable (idempotent)
            try:
                await conn.execute(
                    f"""
                    SELECT create_hypertable('{self.table_name}', 'ts', 
                                           chunk_time_interval => INTERVAL '{self.hypertable_chunk_interval}',
                                           if_not_exists => TRUE)
                """
                )
                logger.info(f"Created hypertable {self.table_name}")
            except Exception as e:
                # Might fail if not a TimescaleDB instance or table already exists
                logger.warning(f"Could not create hypertable: {e}")

            # Create indexes
            indexes = [
                f"CREATE INDEX IF NOT EXISTS idx_{self.table_name}_type_ts ON {self.table_name} (type, ts DESC)",
                f"CREATE INDEX IF NOT EXISTS idx_{self.table_name}_source_ts ON {self.table_name} (source, ts DESC)",
                f"CREATE INDEX IF NOT EXISTS idx_{self.table_name}_data_gin ON {self.table_name} USING GIN (data)",
                f"CREATE INDEX IF NOT EXISTS idx_{self.table_name}_created_at ON {self.table_name} (created_at DESC)",
            ]

            for index_sql in indexes:
                try:
                    await conn.execute(index_sql)
                except Exception as e:
                    logger.warning(f"Failed to create index: {e}")

            await conn.commit()
            logger.info("Tables and indexes created/verified")

    async def insert_events(self, events: List[Dict[str, Any]]) -> bool:
        """Insert a batch of events."""
        if not events:
            return True

        try:
            async with self.pool.connection() as conn:
                # Prepare batch data
                batch_data = []
                for event in events:
                    row_data = self._prepare_event_data(event)
                    batch_data.append(row_data)

                # Batch insert
                insert_sql = f"""
                    INSERT INTO {self.table_name} (ts, type, source, data)
                    VALUES (%s, %s, %s, %s)
                """

                async with conn.cursor() as cursor:
                    await cursor.executemany(insert_sql, batch_data)

                await conn.commit()

                # Update statistics
                self.stats["total_inserts"] += len(events)
                self.stats["total_batches"] += 1
                self.stats["last_insert_time"] = time.time()

                logger.info(
                    "Inserted events batch", count=len(events), table=self.table_name
                )

                return True

        except Exception as e:
            self.stats["total_errors"] += 1
            self.stats["last_error_time"] = time.time()
            logger.error(
                "Failed to insert events",
                error=str(e),
                count=len(events),
                table=self.table_name,
                exc_info=True,
            )
            # Add more context about the failure
            if "null value in column" in str(e).lower():
                logger.error(
                    "Database constraint violation - null value detected", error=str(e)
                )
            elif "connection" in str(e).lower():
                logger.error("Database connection failure during insert", error=str(e))
            raise

    async def insert_single_event(self, event: Dict[str, Any]) -> bool:
        """Insert a single event."""
        return await self.insert_events([event])

    def _prepare_event_data(self, event: Dict[str, Any]) -> tuple:
        """Prepare event data for insertion."""
        # Extract timestamp
        timestamp = self._extract_timestamp(event)

        # Extract type - ensure it's never null/empty
        event_type = event.get("type", "unknown")
        if not event_type or not event_type.strip():
            event_type = "unknown"

        # Extract source - ensure it's never null/empty
        source = self._extract_source(event)
        if not source or not source.strip():
            source = "unknown"

        # Prepare data payload (everything else)
        data = event.copy()

        # Remove fields that are stored in separate columns
        data.pop("timestamp", None)
        data.pop("time", None)
        data.pop("@timestamp", None)

        # Ensure data is never null - serialize as JSON
        json_data = json.dumps(data) if data else "{}"

        return (timestamp, event_type, source, json_data)

    def _extract_timestamp(self, event: Dict[str, Any]) -> datetime:
        """Extract timestamp from event, defaulting to current time."""
        timestamp_fields = ["timestamp", "time", "@timestamp", "ts"]

        for field in timestamp_fields:
            if field in event and event[field]:
                ts_value = event[field]

                if isinstance(ts_value, str):
                    # Try to parse ISO format
                    try:
                        if ts_value.endswith("Z"):
                            return datetime.fromisoformat(ts_value[:-1]).replace(
                                tzinfo=timezone.utc
                            )
                        elif "+" in ts_value or ts_value.count("-") > 2:
                            return datetime.fromisoformat(ts_value)
                        else:
                            # Assume UTC if no timezone
                            dt = datetime.fromisoformat(ts_value)
                            return dt.replace(tzinfo=timezone.utc)
                    except ValueError:
                        continue

                elif isinstance(ts_value, (int, float)):
                    # Unix timestamp
                    return datetime.fromtimestamp(ts_value, tz=timezone.utc)

        # Default to current time
        return datetime.now(timezone.utc)

    def _extract_source(self, event: Dict[str, Any]) -> str:
        """Extract source identifier from event."""
        source_fields = [
            "source",
            "host",
            "hostname",
            "source_host",
            "client_ip",
            "source_ip",
        ]

        for field in source_fields:
            if field in event and event[field]:
                return str(event[field])

        return "unknown"

    async def query_events(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        event_type: Optional[str] = None,
        source: Optional[str] = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Query events with filters."""
        try:
            async with self.pool.connection() as conn:
                conditions = []
                params = []

                if start_time:
                    conditions.append("ts >= %s")
                    params.append(start_time)

                if end_time:
                    conditions.append("ts <= %s")
                    params.append(end_time)

                if event_type:
                    conditions.append("type = %s")
                    params.append(event_type)

                if source:
                    conditions.append("source = %s")
                    params.append(source)

                where_clause = ""
                if conditions:
                    where_clause = "WHERE " + " AND ".join(conditions)

                query = f"""
                    SELECT ts, type, source, data, id, created_at
                    FROM {self.table_name}
                    {where_clause}
                    ORDER BY ts DESC
                    LIMIT %s OFFSET %s
                """

                params.extend([limit, offset])

                async with conn.cursor(row_factory=dict_row) as cursor:
                    await cursor.execute(query, params)
                    rows = await cursor.fetchall()

                    # Convert to list of dicts and merge data
                    results = []
                    for row in rows:
                        result = dict(row)
                        # Merge JSON data back into result
                        if result["data"]:
                            result.update(result["data"])
                        del result["data"]
                        results.append(result)

                    return results

        except Exception as e:
            logger.error("Failed to query events", error=str(e))
            raise

    async def get_stats(self) -> Dict[str, Any]:
        """Get database and writer statistics."""
        try:
            stats = self.stats.copy()

            # Add pool stats
            if self.pool:
                stats["pool"] = {
                    "size": self.pool.get_stats().pool_size,
                    "available": self.pool.get_stats().pool_available,
                    "waiting": self.pool.get_stats().requests_waiting,
                }

            # Add table stats
            async with self.pool.connection() as conn:
                async with conn.cursor() as cursor:
                    # Count total events
                    await cursor.execute(
                        f"SELECT COUNT(*) as count FROM {self.table_name}"
                    )
                    result = await cursor.fetchone()
                    stats["total_events_in_db"] = result[0] if result else 0

                    # Get recent events count (last hour)
                    await cursor.execute(
                        f"""
                        SELECT COUNT(*) as count 
                        FROM {self.table_name} 
                        WHERE created_at > NOW() - INTERVAL '1 hour'
                    """
                    )
                    result = await cursor.fetchone()
                    stats["events_last_hour"] = result[0] if result else 0

            return stats

        except Exception as e:
            logger.error("Failed to get stats", error=str(e))
            return self.stats.copy()

    def get_active_connections(self) -> int:
        """Return the number of active connections in the pool (non-negative)."""
        try:
            if self.pool:
                stats = self.pool.get_stats()
                # Active connections = total - available
                return max(0, stats.pool_size - stats.pool_available)
        except Exception:
            pass
        return 0

    async def health_check(self) -> bool:
        """Perform health check on database connection."""
        try:
            async with self.pool.connection() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute("SELECT 1")
                    result = await cursor.fetchone()
                    return result is not None

        except Exception as e:
            logger.error("Health check failed", error=str(e))
            return False
