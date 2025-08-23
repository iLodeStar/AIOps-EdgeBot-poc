"""Enhanced persistent queue with bandwidth limiting and DLQ support."""
import os
import time
import asyncio
import json
import sqlite3
import threading
import hashlib
from pathlib import Path
from typing import Dict, Any, List, Optional, Set
from datetime import datetime, timezone
import structlog

from .spool import SQLiteSpool

logger = structlog.get_logger(__name__)


class DLQManager:
    """Dead Letter Queue manager for poison messages."""
    
    def __init__(self, dlq_dir: str):
        self.dlq_dir = Path(dlq_dir)
        self.dlq_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
    
    def send_to_dlq(self, message: Dict[str, Any], reason: str, attempts: int = 0):
        """Send a message to the dead letter queue."""
        with self._lock:
            timestamp = datetime.now(timezone.utc).isoformat()
            dlq_entry = {
                'original_message': message,
                'dlq_timestamp': timestamp,
                'reason': reason,
                'attempts': attempts,
                'message_hash': self._hash_message(message)
            }
            
            # Write to DLQ file with timestamp
            dlq_file = self.dlq_dir / f"dlq-{int(time.time())}-{os.getpid()}.json"
            with open(dlq_file, 'w') as f:
                json.dump(dlq_entry, f, indent=2)
            
            logger.warning("Message sent to DLQ",
                          reason=reason,
                          attempts=attempts,
                          dlq_file=str(dlq_file))
    
    def _hash_message(self, message: Dict[str, Any]) -> str:
        """Generate hash for message identification."""
        content = json.dumps(message, sort_keys=True)
        return hashlib.md5(content.encode()).hexdigest()[:8]
    
    def get_dlq_count(self) -> int:
        """Get number of messages in DLQ."""
        return len(list(self.dlq_dir.glob("dlq-*.json")))


class BandwidthLimiter:
    """Token bucket bandwidth limiter."""
    
    def __init__(self, bytes_per_sec: int, burst_bytes: Optional[int] = None):
        self.bytes_per_sec = bytes_per_sec
        self.burst_bytes = burst_bytes or (bytes_per_sec * 2)  # 2 second burst
        self._tokens = float(self.burst_bytes)
        self._last_update = time.time()
        self._lock = threading.Lock()
    
    def can_send(self, byte_count: int) -> bool:
        """Check if we can send the specified number of bytes."""
        with self._lock:
            self._replenish_tokens()
            
            if self._tokens >= byte_count:
                self._tokens -= byte_count
                return True
            return False
    
    def get_wait_time(self, byte_count: int) -> float:
        """Get time to wait before sending the specified bytes."""
        with self._lock:
            self._replenish_tokens()
            
            if self._tokens >= byte_count:
                return 0.0
            
            needed_tokens = byte_count - self._tokens
            return needed_tokens / self.bytes_per_sec
    
    def _replenish_tokens(self):
        """Replenish tokens based on elapsed time."""
        now = time.time()
        elapsed = now - self._last_update
        self._tokens = min(
            self.burst_bytes,
            self._tokens + elapsed * self.bytes_per_sec
        )
        self._last_update = now


class PersistentQueue:
    """Enhanced persistent queue with bandwidth limiting and DLQ."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.enabled = config.get('enabled', False)
        
        if not self.enabled:
            logger.info("Persistent queue disabled")
            return
            
        # Initialize directories
        self.queue_dir = Path(config.get('dir', '/tmp/edgebot_queue'))
        self.queue_dir.mkdir(parents=True, exist_ok=True)
        
        # Queue database
        self.db_path = self.queue_dir / 'queue.db'
        self.spool = SQLiteSpool(str(self.db_path))
        
        # Dead Letter Queue
        dlq_dir = config.get('dlq_dir', self.queue_dir / 'dlq')
        self.dlq = DLQManager(dlq_dir)
        
        # Bandwidth limiting
        bandwidth_limit = config.get('flush_bandwidth_bytes_per_sec', 1024*1024)  # 1MB/s default
        self.bandwidth_limiter = BandwidthLimiter(bandwidth_limit)
        
        # Queue management settings
        self.max_bytes = config.get('max_bytes', 100*1024*1024)  # 100MB
        self.flush_interval_ms = config.get('flush_interval_ms', 5000)  # 5 seconds
        self.max_attempts = 5  # Max attempts before DLQ
        
        # State tracking
        self._running = False
        self._flush_task = None
        
        logger.info("Persistent queue initialized",
                   queue_dir=str(self.queue_dir),
                   max_bytes=self.max_bytes,
                   flush_interval_ms=self.flush_interval_ms,
                   bandwidth_limit=bandwidth_limit)
    
    async def start(self):
        """Start the queue flush task."""
        if not self.enabled:
            return
            
        self._running = True
        self._flush_task = asyncio.create_task(self._flush_loop())
        logger.info("Persistent queue started")
    
    async def stop(self):
        """Stop the queue and flush remaining messages."""
        if not self.enabled or not self._running:
            return
            
        self._running = False
        
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
        
        # Final flush attempt
        await self._flush_ready_messages()
        logger.info("Persistent queue stopped")
    
    def enqueue(self, message: Dict[str, Any]) -> bool:
        """Add message to the persistent queue."""
        if not self.enabled:
            return True  # Pass-through if disabled
            
        try:
            # Check if queue is approaching capacity
            current_size = self.get_current_size_bytes()
            message_size = len(json.dumps(message).encode('utf-8'))
            
            if current_size + message_size > self.max_bytes:
                logger.warning("Queue approaching capacity, applying backpressure",
                              current_size=current_size,
                              max_bytes=self.max_bytes,
                              message_size=message_size)
                return False
            
            # Add attempt tracking metadata
            queue_message = message.copy()
            queue_message['__queue_timestamp'] = time.time()
            queue_message['__queue_attempts'] = 0
            
            self.spool.put(queue_message)
            return True
            
        except Exception as e:
            logger.error("Failed to enqueue message", error=str(e))
            return False
    
    async def _flush_loop(self):
        """Main flush loop that sends queued messages."""
        while self._running:
            try:
                await self._flush_ready_messages()
                await asyncio.sleep(self.flush_interval_ms / 1000.0)
            except asyncio.CancelledError:
                logger.info("Queue flush loop cancelled")
                break
            except Exception as e:
                logger.error("Error in flush loop", error=str(e))
                await asyncio.sleep(1)
    
    async def _flush_ready_messages(self):
        """Flush messages that are ready to be sent."""
        if not self.enabled:
            return
            
        # Get batch of pending messages
        batch_size = 100  # Process in smaller batches to avoid memory issues
        messages = self.spool.get_batch(batch_size)
        
        if not messages:
            return
        
        # Calculate total batch size for bandwidth limiting
        batch_json = json.dumps(messages)
        batch_bytes = len(batch_json.encode('utf-8'))
        
        # Check bandwidth limit
        if not self.bandwidth_limiter.can_send(batch_bytes):
            wait_time = self.bandwidth_limiter.get_wait_time(batch_bytes)
            if wait_time > 0:
                logger.debug("Bandwidth limit reached, waiting",
                           wait_time=wait_time,
                           batch_bytes=batch_bytes)
                await asyncio.sleep(wait_time)
                # Try again after waiting
                if not self.bandwidth_limiter.can_send(batch_bytes):
                    return  # Skip this round
        
        # Process messages (this would typically send to mothership)
        success_count = 0
        failed_messages = []
        
        for message in messages:
            try:
                # Simulate processing - in real implementation, this would send to mothership
                success = await self._process_message(message)
                
                if success:
                    success_count += 1
                else:
                    failed_messages.append(message)
                    
            except Exception as e:
                logger.error("Error processing queued message", error=str(e))
                failed_messages.append(message)
        
        # Commit successful messages
        if success_count > 0:
            successful_messages = [msg for msg in messages if msg not in failed_messages]
            self.spool.commit_batch(successful_messages, True)
        
        # Handle failed messages
        for message in failed_messages:
            await self._handle_failed_message(message)
        
        if messages:
            logger.debug("Queue flush completed",
                        total_messages=len(messages),
                        successful=success_count,
                        failed=len(failed_messages))
    
    async def _process_message(self, message: Dict[str, Any]) -> bool:
        """Process a single message (placeholder - would send to mothership)."""
        # This is a placeholder - in the real implementation, this would
        # send the message to the mothership via the DataShipper
        
        # Simulate some processing time and potential failure
        await asyncio.sleep(0.01)  # Small delay to simulate network call
        
        # For testing, simulate 90% success rate
        import random
        return random.random() > 0.1
    
    async def _handle_failed_message(self, message: Dict[str, Any]):
        """Handle a failed message - retry or send to DLQ."""
        attempts = message.get('__queue_attempts', 0) + 1
        message['__queue_attempts'] = attempts
        message['__queue_last_failure'] = time.time()
        
        if attempts >= self.max_attempts:
            # Send to DLQ
            self.dlq.send_to_dlq(message, "max_attempts_exceeded", attempts)
            # Remove from main queue
            self.spool.commit_batch([message], True)  # Mark as processed
        else:
            # Update message with new attempt count and put back in queue
            self.spool.put(message)
            # Remove old version
            self.spool.commit_batch([message], True)
    
    def get_current_size_bytes(self) -> int:
        """Get current queue size in bytes (approximate)."""
        if not self.enabled:
            return 0
            
        # This is an approximation - in a real implementation you'd track this more precisely
        message_count = self.spool.size()
        avg_message_size = 1024  # Assume 1KB average message size
        return message_count * avg_message_size
    
    def get_stats(self) -> Dict[str, Any]:
        """Get queue statistics."""
        if not self.enabled:
            return {'enabled': False}
            
        spool_stats = self.spool.get_stats()
        return {
            'enabled': True,
            'pending_messages': spool_stats.get('pending', 0),
            'total_messages': spool_stats.get('total_messages', 0),
            'completed_messages': spool_stats.get('completed', 0),
            'failed_messages': spool_stats.get('failed', 0),
            'dlq_messages': self.dlq.get_dlq_count(),
            'current_size_bytes': self.get_current_size_bytes(),
            'max_bytes': self.max_bytes,
            'bandwidth_limit_bps': self.bandwidth_limiter.bytes_per_sec,
            'queue_dir': str(self.queue_dir),
            'running': self._running
        }
    
    def is_healthy(self) -> bool:
        """Check if queue is healthy."""
        if not self.enabled:
            return True
            
        # Check if queue is not too full
        current_size = self.get_current_size_bytes()
        utilization = current_size / self.max_bytes if self.max_bytes > 0 else 0
        
        # Consider unhealthy if more than 80% full
        return utilization < 0.8