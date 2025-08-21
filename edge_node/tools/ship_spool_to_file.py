#!/usr/bin/env python3
"""Ship spool contents to file using EdgeBot DataShipper."""

import sys
import os
import asyncio
import argparse
import tempfile
import yaml
from typing import Dict, Any

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.output.shipper import OutputShipper, MessageBuffer


async def ship_to_file(buffer_path: str, output_dir: str, batch_size: int = 100):
    """Ship spool contents to file."""
    
    # Create file:// URL for output directory
    file_url = f"file://{os.path.abspath(output_dir)}"
    
    # Create configuration for the shipper
    config = {
        'buffer': {
            'max_size': 10000,
            'disk_buffer': True,
            'disk_buffer_path': buffer_path
        },
        'mothership': {
            'url': file_url,
            'batch_size': batch_size,
            'batch_timeout': 1.0,  # Process quickly for tool usage
            'compression': True,
            'max_retries': 1
        }
    }
    
    print(f"Shipping spool from {buffer_path} to {output_dir}")
    print(f"Batch size: {batch_size}")
    print(f"Output URL: {file_url}")
    
    # Create output shipper
    shipper = OutputShipper(config)
    
    try:
        # Start the shipper
        await shipper.start()
        
        # Check initial buffer size
        initial_stats = shipper.buffer.get_stats()
        pending_messages = initial_stats.get('current_size', 0)
        print(f"Initial pending messages: {pending_messages}")
        
        if pending_messages == 0:
            print("No messages to ship")
            return
        
        # Let it run until buffer is empty
        print("Shipping messages...")
        
        shipped_count = 0
        max_wait_cycles = 100  # Prevent infinite loops
        wait_cycle = 0
        
        while wait_cycle < max_wait_cycles:
            await asyncio.sleep(0.5)  # Give shipper time to work
            
            current_stats = shipper.buffer.get_stats()
            current_pending = current_stats.get('current_size', 0)
            
            if current_pending == 0:
                print("All messages shipped")
                break
            
            # Show progress
            if wait_cycle % 10 == 0:
                shipped = pending_messages - current_pending
                print(f"Progress: {shipped}/{pending_messages} messages shipped")
            
            wait_cycle += 1
        
        if wait_cycle >= max_wait_cycles:
            print("Warning: Maximum wait time reached, some messages may not have been shipped")
        
        # Final statistics
        final_stats = shipper.buffer.get_stats()
        shipper_stats = shipper.shipper.get_stats()
        
        print(f"\nFinal statistics:")
        print(f"  Total batches sent: {shipper_stats['total_batches_sent']}")
        print(f"  Total messages sent: {shipper_stats['total_messages_sent']}")
        print(f"  Total bytes sent: {shipper_stats['total_bytes_sent']}")
        print(f"  Failures: {shipper_stats['total_failures']}")
        print(f"  Remaining pending: {final_stats.get('current_size', 0)}")
        print(f"  Completed messages: {final_stats.get('completed_messages', 0)}")
        
    finally:
        await shipper.stop()


def main():
    """Main function."""
    parser = argparse.ArgumentParser(description='Ship EdgeBot spool contents to files')
    parser.add_argument('--buffer-path', 
                       default='/tmp/edgebot_buffer.db',
                       help='Path to SQLite buffer database')
    parser.add_argument('--output-dir', 
                       required=True,
                       help='Output directory for payload files')
    parser.add_argument('--batch-size', type=int, default=100,
                       help='Batch size for shipping')
    parser.add_argument('--create-output-dir', action='store_true',
                       help='Create output directory if it does not exist')
    
    args = parser.parse_args()
    
    if not os.path.exists(args.buffer_path):
        print(f"Error: Buffer database '{args.buffer_path}' not found", file=sys.stderr)
        sys.exit(1)
    
    if not os.path.exists(args.output_dir):
        if args.create_output_dir:
            os.makedirs(args.output_dir, exist_ok=True)
            print(f"Created output directory: {args.output_dir}")
        else:
            print(f"Error: Output directory '{args.output_dir}' not found", file=sys.stderr)
            print("Use --create-output-dir to create it automatically")
            sys.exit(1)
    
    if not os.path.isdir(args.output_dir):
        print(f"Error: '{args.output_dir}' is not a directory", file=sys.stderr)
        sys.exit(1)
    
    # Run the async shipping process
    try:
        asyncio.run(ship_to_file(args.buffer_path, args.output_dir, args.batch_size))
        
        # List generated files
        print(f"\nGenerated files in {args.output_dir}:")
        for filename in sorted(os.listdir(args.output_dir)):
            if filename.startswith('payload-'):
                filepath = os.path.join(args.output_dir, filename)
                size = os.path.getsize(filepath)
                print(f"  {filename} ({size} bytes)")
        
    except KeyboardInterrupt:
        print("\nShipping interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"Error during shipping: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()