"""Output shipper for EdgeBot - streams data to mothership."""
import asyncio
import json
import gzip
import time
import os
import aiofiles
from collections import deque
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Callable
from urllib.parse import urlparse
import httpx
import structlog
from .spool import SQLiteSpool

logger = structlog.get_logger(__name__)


def build_sanitized_envelope(batch_messages: List[Dict[str, Any]], is_retry: bool = False) -> str:
    """Build sanitized envelope from batch messages, removing all internal fields.
    
    This ensures a single source of truth for outbound payloads by:
    1. Removing any keys starting with "__" (like __spool_id, __spool_timestamp)
    2. Removing other internal spool metadata: status, attempts, last_error, enqueued_at
    3. Building a consistent envelope structure
    
    Args:
        batch_messages: List of raw messages from spool
        is_retry: Whether this is a retry attempt
        
    Returns:
        JSON string ready for output (both .json and .json.gz)
    """
    # Internal field keys to remove
    internal_fields = {'status', 'attempts', 'last_error', 'enqueued_at'}
    
    # Sanitize messages by removing internal fields
    sanitized_messages = []
    for message in batch_messages:
        # Remove any keys starting with "__" and specific internal fields
        clean_message = {
            k: v for k, v in message.items() 
            if not k.startswith('__') and k not in internal_fields
        }
        sanitized_messages.append(clean_message)
    
    # Build consistent envelope structure
    envelope = {
        'messages': sanitized_messages,
        'batch_size': len(sanitized_messages),
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'source': 'edgebot',
        'is_retry': is_retry
    }
    
    # Convert to JSON string (single source of truth)
    return json.dumps(envelope, separators=(',', ':'))


class MessageBuffer:
    """Bounded message buffer with optional disk backing."""
    
    def __init__(self, max_size: int = 10000, disk_buffer: bool = False, 
                 disk_path: Optional[str] = None):
        self.max_size = max_size
        self.disk_buffer = disk_buffer
        self.disk_path = disk_path
        self._dropped_messages = 0
        self._total_messages = 0
        
        if disk_buffer and disk_path:
            # Use SQLite spool for persistent storage
            self._spool = SQLiteSpool(disk_path)
            self._queue = None
            logger.info("MessageBuffer using SQLite spool", path=disk_path)
        else:
            # Use in-memory deque
            self._spool = None
            self._queue = deque(maxlen=max_size)
            logger.info("MessageBuffer using in-memory queue", max_size=max_size)
    
    def put(self, message: Dict[str, Any]) -> bool:
        """Add a message to the buffer."""
        self._total_messages += 1
        
        # Add timestamp if not present
        if 'timestamp' not in message:
            message['timestamp'] = datetime.now(timezone.utc).isoformat()
        
        if self._spool:
            # SQLite spool handles persistence
            try:
                self._spool.put(message)
                return True
            except Exception as e:
                logger.error("Failed to add message to spool", error=str(e))
                self._dropped_messages += 1
                return False
        else:
            # In-memory queue with size limit
            if len(self._queue) >= self.max_size:
                self._dropped_messages += 1
                logger.warning("Message buffer full, dropping message",
                              buffer_size=len(self._queue), dropped=self._dropped_messages)
                return False
            
            self._queue.append(message)
            return True
    
    def get_batch(self, batch_size: int) -> List[Dict[str, Any]]:
        """Get a batch of messages."""
        if self._spool:
            return self._spool.get_batch(batch_size)
        else:
            batch = []
            for _ in range(min(batch_size, len(self._queue))):
                if self._queue:
                    batch.append(self._queue.popleft())
            return batch
    
    def commit_batch(self, messages: List[Dict[str, Any]], success: bool):
        """Commit or rollback a batch of messages (only for SQLite spool)."""
        if self._spool:
            self._spool.commit_batch(messages, success)
    
    def size(self) -> int:
        """Get current buffer size."""
        if self._spool:
            return self._spool.size()
        else:
            return len(self._queue)
    
    def is_empty(self) -> bool:
        """Check if buffer is empty."""
        return self.size() == 0
    
    def get_stats(self) -> Dict[str, Any]:
        """Get buffer statistics."""
        if self._spool:
            spool_stats = self._spool.get_stats()
            return {
                'current_size': spool_stats['pending'],
                'max_size': self.max_size,  # Not applicable for SQLite but keep for compatibility
                'total_messages': spool_stats['total_messages'],
                'completed_messages': spool_stats['completed'],
                'failed_messages': spool_stats['failed'],
                'dropped_messages': self._dropped_messages,
                'disk_buffer': True,
                'db_path': spool_stats['db_path']
            }
        else:
            return {
                'current_size': len(self._queue),
                'max_size': self.max_size,
                'total_messages': self._total_messages,
                'dropped_messages': self._dropped_messages,
                'utilization': len(self._queue) / self.max_size if self.max_size > 0 else 0,
                'disk_buffer': False
            }


class RetryManager:
    """Manages retry logic for failed requests."""
    
    def __init__(self, max_retries: int = 3, base_backoff: float = 1.0, max_backoff: float = 60.0):
        self.max_retries = max_retries
        self.base_backoff = base_backoff
        self.max_backoff = max_backoff
        self._retry_batches = []  # List of (batch, attempt_count, next_retry_time)
    
    def add_failed_batch(self, batch: List[Dict[str, Any]]):
        """Add a failed batch for retry."""
        next_retry_time = time.time() + self.base_backoff
        self._retry_batches.append((batch, 1, next_retry_time))
    
    def get_ready_batches(self) -> List[List[Dict[str, Any]]]:
        """Get batches that are ready for retry."""
        ready_batches = []
        remaining_batches = []
        current_time = time.time()
        
        for batch, attempt_count, next_retry_time in self._retry_batches:
            if current_time >= next_retry_time:
                if attempt_count <= self.max_retries:
                    ready_batches.append(batch)
                    # Calculate next retry time with exponential backoff
                    backoff = min(self.base_backoff * (2 ** attempt_count), self.max_backoff)
                    remaining_batches.append((batch, attempt_count + 1, current_time + backoff))
                else:
                    logger.warning("Batch exceeded max retries, dropping",
                                 messages=len(batch), attempts=attempt_count)
            else:
                remaining_batches.append((batch, attempt_count, next_retry_time))
        
        self._retry_batches = remaining_batches
        return ready_batches
    
    def get_stats(self) -> Dict[str, Any]:
        """Get retry manager statistics."""
        return {
            'pending_retries': len(self._retry_batches),
            'total_messages_in_retry': sum(len(batch) for batch, _, _ in self._retry_batches)
        }


class RateLimiter:
    """Token bucket rate limiter."""
    
    def __init__(self, rate: float, burst: int):
        self.rate = rate  # tokens per second
        self.burst = burst  # bucket size
        self._tokens = float(burst)
        self._last_update = time.time()
    
    def can_proceed(self, tokens_needed: int = 1) -> bool:
        """Check if we can proceed with the request."""
        now = time.time()
        # Add tokens based on elapsed time
        elapsed = now - self._last_update
        self._tokens = min(self.burst, self._tokens + elapsed * self.rate)
        self._last_update = now
        
        if self._tokens >= tokens_needed:
            self._tokens -= tokens_needed
            return True
        return False
    
    def get_wait_time(self, tokens_needed: int = 1) -> float:
        """Get time to wait before proceeding."""
        if self.can_proceed(tokens_needed):
            return 0.0
        
        needed = tokens_needed - self._tokens
        return needed / self.rate


class DataShipper:
    """Handles shipping data to the mothership with batching, compression, and retries."""
    
    def __init__(self, config: Dict[str, Any], buffer: MessageBuffer):
        self.config = config
        self.buffer = buffer
        self.running = False
        self.ship_task = None
        
        # HTTP client
        self.client = None
        
        # Retry management
        self.retry_manager = RetryManager(
            max_retries=config.get('max_retries', 3),
            base_backoff=config.get('retry_backoff', 1.0)
        )
        
        # Rate limiting
        rate_limit = config.get('rate_limit', {})
        self.rate_limiter = RateLimiter(
            rate=rate_limit.get('requests_per_second', 10.0),
            burst=rate_limit.get('burst', 20)
        ) if rate_limit.get('enabled', False) else None
        
        # Statistics
        self.stats = {
            'total_batches_sent': 0,
            'total_messages_sent': 0,
            'total_bytes_sent': 0,
            'total_failures': 0,
            'last_successful_send': None,
            'last_failure': None
        }
    
    async def start(self):
        """Start the data shipper."""
        # Check if we need HTTP client (not file:// URL)
        url = self.config.get('url', '')
        parsed_url = urlparse(url)
        
        if parsed_url.scheme not in ('file', ''):
            # Create HTTP client for HTTP/HTTPS
            timeout = httpx.Timeout(
                connect=self.config.get('connect_timeout', 10),
                read=self.config.get('read_timeout', 30),
                write=self.config.get('write_timeout', 10),
                pool=self.config.get('pool_timeout', 10)
            )
            
            # TLS configuration
            verify = self.config.get('tls_verify', True)
            cert = None
            if self.config.get('tls_client_cert') and self.config.get('tls_client_key'):
                cert = (self.config['tls_client_cert'], self.config['tls_client_key'])
            
            self.client = httpx.AsyncClient(
                timeout=timeout,
                verify=verify,
                cert=cert,
                follow_redirects=True,
                headers={'User-Agent': 'EdgeBot-Shipper/1.0'}
            )
        else:
            # No HTTP client needed for file:// URLs
            self.client = None
        
        self.running = True
        self.ship_task = asyncio.create_task(self._ship_loop())
        
        logger.info("Data shipper started", 
                   url=self.config.get('url'),
                   batch_size=self.config.get('batch_size', 100),
                   scheme=parsed_url.scheme or 'http')
    
    async def stop(self):
        """Stop the data shipper."""
        if not self.running:
            return
        
        self.running = False
        
        if self.ship_task:
            self.ship_task.cancel()
            try:
                await self.ship_task
            except asyncio.CancelledError:
                pass
        
        if self.client:
            await self.client.aclose()
        
        logger.info("Data shipper stopped")
    
    async def _ship_loop(self):
        """Main shipping loop."""
        batch_size = self.config.get('batch_size', 100)
        batch_timeout = self.config.get('batch_timeout', 5.0)
        
        last_batch_time = time.time()
        
        while self.running:
            try:
                current_time = time.time()
                
                # Check for retry batches
                retry_batches = self.retry_manager.get_ready_batches()
                for retry_batch in retry_batches:
                    await self._send_batch(retry_batch, is_retry=True)
                
                # Check if we should send a new batch
                should_send = (
                    self.buffer.size() >= batch_size or
                    (self.buffer.size() > 0 and current_time - last_batch_time >= batch_timeout)
                )
                
                if should_send:
                    batch = self.buffer.get_batch(batch_size)
                    if batch:
                        await self._send_batch(batch)
                        last_batch_time = current_time
                
                # Small sleep to prevent busy waiting
                await asyncio.sleep(0.1)
                
            except asyncio.CancelledError:
                logger.info("Data shipper loop cancelled")
                break
            except Exception as e:
                logger.error("Error in shipping loop", error=str(e))
                await asyncio.sleep(1)
    
    async def _send_batch(self, batch: List[Dict[str, Any]], is_retry: bool = False):
        """Send a batch of messages to the mothership."""
        if not batch:
            return
        
        success = False
        
        try:
            # Rate limiting
            if self.rate_limiter:
                wait_time = self.rate_limiter.get_wait_time()
                if wait_time > 0:
                    await asyncio.sleep(wait_time)
            
            # Build sanitized envelope (single source of truth)
            json_data = build_sanitized_envelope(batch, is_retry)
            
            # Check if URL is file:// scheme
            url = self.config.get('url', '')
            parsed_url = urlparse(url)
            
            if parsed_url.scheme == 'file':
                # File-based output
                await self._write_to_file(json_data, parsed_url.path)
                success = True
            else:
                # HTTP-based output
                success = await self._send_http_batch(json_data, batch)
            
            if success:
                # Update statistics
                self.stats['total_batches_sent'] += 1
                self.stats['total_messages_sent'] += len(batch)
                self.stats['total_bytes_sent'] += len(json_data.encode('utf-8'))
                self.stats['last_successful_send'] = time.time()
                
                logger.debug("Batch sent successfully",
                           messages=len(batch), success=success)
        
        except Exception as e:
            self.stats['total_failures'] += 1
            self.stats['last_failure'] = time.time()
            
            logger.error("Error sending batch",
                        error=str(e), messages=len(batch))
            if not is_retry:
                self.retry_manager.add_failed_batch(batch)
        
        finally:
            # Commit or rollback the batch in the buffer
            self.buffer.commit_batch(batch, success)
    
    async def _write_to_file(self, json_data: str, base_path: str):
        """Write payload to file with gzip compression and plain JSON copy."""
        try:
            # Create output directory with better error handling
            os.makedirs(base_path, exist_ok=True)
        except OSError as e:
            error_msg = f"Failed to create output directory '{base_path}': {e}"
            logger.error(error_msg)
            raise RuntimeError(error_msg) from e
        
        # Generate filename with timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:-3]  # milliseconds
        
        # Write gzipped payload
        gzip_filename = f"payload-{timestamp}.json.gz"
        gzip_path = os.path.join(base_path, gzip_filename)
        
        compressed_data = gzip.compress(json_data.encode('utf-8'))
        async with aiofiles.open(gzip_path, 'wb') as f:
            await f.write(compressed_data)
        
        # Write plain JSON for readability
        json_filename = f"payload-{timestamp}.json"
        json_path = os.path.join(base_path, json_filename)
        
        async with aiofiles.open(json_path, 'w') as f:
            await f.write(json_data)
        
        logger.info("Payload written to files", 
                   gzip_file=gzip_path, 
                   json_file=json_path,
                   size_bytes=len(json_data))
    
    async def _send_http_batch(self, json_data: str, batch: List[Dict[str, Any]]) -> bool:
        """Send batch via HTTP/HTTPS."""
        try:
            # Compression
            if self.config.get('compression', True):
                data = gzip.compress(json_data.encode('utf-8'))
                headers = {
                    'Content-Type': 'application/json',
                    'Content-Encoding': 'gzip'
                }
            else:
                data = json_data.encode('utf-8')
                headers = {'Content-Type': 'application/json'}
            
            # Authentication
            if self.config.get('auth_token'):
                headers['Authorization'] = f"Bearer {self.config['auth_token']}"
            
            # Send request
            logger.debug("Sending batch to mothership", 
                        messages=len(batch), bytes=len(data))
            
            response = await self.client.post(
                self.config['url'],
                content=data,
                headers=headers
            )
            
            response.raise_for_status()
            
            logger.debug("HTTP batch sent successfully",
                        messages=len(batch), status=response.status_code)
            return True
            
        except httpx.HTTPStatusError as e:
            # Don't retry client errors (4xx)
            if 400 <= e.response.status_code < 500:
                logger.error("Client error sending batch, not retrying",
                           status=e.response.status_code, messages=len(batch))
            else:
                logger.warning("Server error sending batch, will retry",
                             status=e.response.status_code, messages=len(batch))
                raise  # Re-raise to trigger retry
            return False
            
        except (httpx.RequestError, asyncio.TimeoutError) as e:
            logger.warning("Network error sending batch, will retry",
                          error=str(e), messages=len(batch))
            raise  # Re-raise to trigger retry
    
    def get_stats(self) -> Dict[str, Any]:
        """Get shipping statistics."""
        stats = self.stats.copy()
        stats['buffer'] = self.buffer.get_stats()
        stats['retry'] = self.retry_manager.get_stats()
        stats['running'] = self.running
        return stats


class OutputShipper:
    """Main output shipper coordinating buffer and shipping."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        
        # Create buffer
        buffer_config = config.get('buffer', {})
        self.buffer = MessageBuffer(
            max_size=buffer_config.get('max_size', 10000),
            disk_buffer=buffer_config.get('disk_buffer', False),
            disk_path=buffer_config.get('disk_buffer_path')
        )
        
        # Create shipper
        mothership_config = config.get('mothership', {})
        self.shipper = DataShipper(mothership_config, self.buffer)
        
    async def start(self):
        """Start the output shipper."""
        await self.shipper.start()
        logger.info("Output shipper started")
    
    async def stop(self):
        """Stop the output shipper."""
        await self.shipper.stop()
        logger.info("Output shipper stopped")
    
    async def send_message(self, message: Dict[str, Any]):
        """Send a message (adds to buffer for batching)."""
        self.buffer.put(message)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get output shipper statistics."""
        return self.shipper.get_stats()
    
    def is_healthy(self) -> bool:
        """Check if the output shipper is healthy."""
        stats = self.get_stats()
        
        # Check if we're dropping too many messages
        buffer_stats = stats.get('buffer', {})
        utilization = buffer_stats.get('utilization', 0)
        
        # Check if we've had recent successful sends
        last_success = stats.get('last_successful_send')
        if last_success:
            time_since_success = time.time() - last_success
            # Consider unhealthy if no success in 10 minutes
            if time_since_success > 600:
                return False
        
        # Consider unhealthy if buffer is more than 90% full
        return utilization < 0.9


# Factory function for creating output shipper
def create_output_shipper(config: Dict[str, Any]) -> OutputShipper:
    """Create an output shipper instance."""
    return OutputShipper(config)