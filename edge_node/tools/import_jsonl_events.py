#!/usr/bin/env python3
"""Import JSONL syslog events into the EdgeBot message buffer."""

import sys
import os
import json
import argparse
import re
import zoneinfo
from datetime import datetime, timezone
from typing import Dict, Any, Optional

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.output.shipper import MessageBuffer

# Syslog severity to RFC5424 numeric mapping
SEVERITY_MAP = {
    'emergency': 0, 'emerg': 0,
    'alert': 1,
    'critical': 2, 'crit': 2,
    'error': 3, 'err': 3,
    'warning': 4, 'warn': 4,
    'notice': 5,
    'informational': 6, 'info': 6,
    'debug': 7,
}


def normalize_syslog_event(event: Dict[str, Any], tz: Optional[str] = None, map_severity: bool = False) -> Dict[str, Any]:
    """Normalize a syslog event into EdgeBot format."""
    
    # Start with the original event as base
    message = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'type': 'syslog_event',
        'source': 'jsonl-import',
        'raw_message': str(event.get('message', event.get('msg', ''))),
        'rfc_variant': None
    }
    
    # Extract timestamp
    timestamp_fields = ['timestamp', 'time', '@timestamp', 'datetime', 'ts']
    for field in timestamp_fields:
        if field in event and event[field]:
            try:
                timestamp_str = str(event[field])
                # Try various timestamp formats
                if timestamp_str.isdigit():
                    # Unix timestamp
                    timestamp = datetime.fromtimestamp(float(timestamp_str), tz=timezone.utc)
                elif 'T' in timestamp_str:
                    # ISO format
                    timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                else:
                    # Try other common formats
                    for fmt in [
                        '%Y-%m-%d %H:%M:%S',
                        '%Y-%m-%d %H:%M:%S.%f',
                        '%b %d %H:%M:%S',
                        '%Y/%m/%d %H:%M:%S'
                    ]:
                        try:
                            timestamp = datetime.strptime(timestamp_str, fmt)
                            if timestamp.tzinfo is None:
                                if tz:
                                    # Apply specified timezone and convert to UTC
                                    local_tz = zoneinfo.ZoneInfo(tz)
                                    timestamp = timestamp.replace(tzinfo=local_tz)
                                    timestamp = timestamp.astimezone(timezone.utc)
                                else:
                                    # Default behavior: treat as UTC
                                    timestamp = timestamp.replace(tzinfo=timezone.utc)
                            break
                        except ValueError:
                            continue
                    else:
                        timestamp = datetime.now(timezone.utc)
                
                message['timestamp'] = timestamp.isoformat()
                break
            except (ValueError, TypeError):
                continue
    
    # Extract source IP/host information
    source_fields = ['source_ip', 'host', 'hostname', 'source_host', 'src_ip', 'client_ip']
    for field in source_fields:
        if field in event and event[field]:
            message['source_ip'] = str(event[field])
            break
    
    # Extract port if available
    port_fields = ['source_port', 'port', 'src_port']
    for field in port_fields:
        if field in event and event[field]:
            try:
                message['source_port'] = int(event[field])
            except (ValueError, TypeError):
                pass
            break
    
    # Extract syslog-specific fields
    syslog_mappings = {
        'facility': ['facility', 'fac'],
        'severity': ['severity', 'sev', 'level'],
        'priority': ['priority', 'pri'],
        'tag': ['tag', 'ident', 'program', 'process'],
        'pid': ['pid', 'process_id', 'proc_id']
    }
    
    for dest_field, source_fields in syslog_mappings.items():
        for field in source_fields:
            if field in event and event[field] is not None:
                if dest_field in ['priority', 'severity', 'pid']:
                    try:
                        message[dest_field] = int(event[field])
                    except (ValueError, TypeError):
                        message[dest_field] = str(event[field])
                else:
                    message[dest_field] = str(event[field])
                break
    
    # Extract additional structured data
    structured_fields = ['structured_data', 'sd', 'data']
    for field in structured_fields:
        if field in event and event[field]:
            message['structured_data'] = event[field]
            break
    
    # Add numeric severity mapping if requested
    if map_severity and 'severity' in message:
        severity_str = str(message['severity']).lower()
        if severity_str in SEVERITY_MAP:
            message['severity_num'] = SEVERITY_MAP[severity_str]
        elif isinstance(message['severity'], int):
            # Already numeric, just copy
            message['severity_num'] = message['severity']
    
    # Detect RFC variant based on message format
    raw_msg = message.get('raw_message', '')
    if raw_msg:
        # RFC5424 pattern (simplified)
        if re.match(r'<\d+>\d+\s+\S+\s+\S+\s+\S+\s+\S+\s+\S+\s+(\[.*?\]|\-)', raw_msg):
            message['rfc_variant'] = 'RFC5424'
        # RFC3164 pattern (simplified)
        elif re.match(r'<\d+>\w+\s+\d+\s+\d+:\d+:\d+', raw_msg):
            message['rfc_variant'] = 'RFC3164'
    
    # Copy any additional fields not already mapped
    exclude_fields = set([
        'timestamp', 'time', '@timestamp', 'datetime', 'ts',
        'message', 'msg', 'source_ip', 'host', 'hostname', 'source_host', 
        'src_ip', 'client_ip', 'source_port', 'port', 'src_port',
        'facility', 'fac', 'severity', 'sev', 'level', 'priority', 'pri',
        'tag', 'ident', 'program', 'process', 'pid', 'process_id', 'proc_id',
        'structured_data', 'sd', 'data'
    ])
    
    for key, value in event.items():
        if key not in exclude_fields and not key.startswith('_'):
            message[f'extra_{key}'] = value
    
    return message


def normalize_snmp_metric(event: Dict[str, Any], tz: Optional[str] = None, percent_as_ratio: bool = False) -> Dict[str, Any]:
    """Normalize an SNMP metric event into EdgeBot format."""
    
    # Start with the original event as base
    message = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'type': 'snmp_metric',
        'source': 'jsonl-import'
    }
    
    # Extract timestamp with timezone support
    timestamp_fields = ['timestamp', 'time', '@timestamp', 'datetime', 'ts']
    for field in timestamp_fields:
        if field in event and event[field]:
            try:
                timestamp_str = str(event[field])
                # Try various timestamp formats
                if timestamp_str.isdigit():
                    # Unix timestamp
                    timestamp = datetime.fromtimestamp(float(timestamp_str), tz=timezone.utc)
                elif 'T' in timestamp_str:
                    # ISO format
                    timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                else:
                    # Try other common formats
                    for fmt in [
                        '%Y-%m-%d %H:%M:%S',
                        '%Y-%m-%d %H:%M:%S.%f',
                        '%b %d %H:%M:%S',
                        '%Y/%m/%d %H:%M:%S'
                    ]:
                        try:
                            timestamp = datetime.strptime(timestamp_str, fmt)
                            if timestamp.tzinfo is None:
                                if tz:
                                    # Apply specified timezone and convert to UTC
                                    local_tz = zoneinfo.ZoneInfo(tz)
                                    timestamp = timestamp.replace(tzinfo=local_tz)
                                    timestamp = timestamp.astimezone(timezone.utc)
                                else:
                                    # Default behavior: treat as UTC
                                    timestamp = timestamp.replace(tzinfo=timezone.utc)
                            break
                        except ValueError:
                            continue
                    else:
                        timestamp = datetime.now(timezone.utc)
                
                message['timestamp'] = timestamp.isoformat()
                break
            except (ValueError, TypeError):
                continue
    
    # Map common SNMP fields directly
    snmp_mappings = {
        'host': ['host', 'hostname', 'target'],
        'oid': ['oid'],
        'metric_name': ['metric_name', 'name', 'metric'],
        'value': ['value'],
        'unit': ['unit', 'units'],
        'interface': ['interface', 'interface_name', 'ifDescr'],
        'community': ['community'],
        'snmp_version': ['snmp_version', 'version']
    }
    
    for dest_field, source_fields in snmp_mappings.items():
        for field in source_fields:
            if field in event and event[field] is not None:
                if dest_field == 'value':
                    try:
                        message[dest_field] = float(event[field])
                    except (ValueError, TypeError):
                        message[dest_field] = event[field]
                else:
                    message[dest_field] = str(event[field])
                break
    
    # Handle percent-as-ratio conversion
    if percent_as_ratio and message.get('unit') == '%' and 'value' in message:
        try:
            value = float(message['value'])
            message['value_ratio'] = value / 100.0
        except (ValueError, TypeError):
            pass  # Keep original value if conversion fails
    
    # Copy any additional fields not already mapped
    exclude_fields = set([
        'timestamp', 'time', '@timestamp', 'datetime', 'ts',
        'host', 'hostname', 'target', 'oid', 'metric_name', 'name', 'metric',
        'value', 'unit', 'units', 'interface', 'interface_name', 'ifDescr',
        'community', 'snmp_version', 'version'
    ])
    
    for key, value in event.items():
        if key not in exclude_fields and not key.startswith('_'):
            message[f'extra_{key}'] = value
    
    return message


def main():
    """Main function."""
    parser = argparse.ArgumentParser(description='Import JSONL events into EdgeBot buffer')
    parser.add_argument('jsonl_file', nargs='?', help='Path to the JSONL file to import (use - for stdin)')
    parser.add_argument('--stdin', action='store_true', 
                       help='Read from stdin instead of file')
    parser.add_argument('--record-type', choices=['syslog_event', 'snmp_metric'], default='syslog_event',
                       help='Type of records to import (default: syslog_event)')
    parser.add_argument('--buffer-path', help='Path to SQLite buffer database', 
                       default='/tmp/edgebot_buffer.db')
    parser.add_argument('--use-memory', action='store_true', 
                       help='Use in-memory buffer instead of SQLite')
    parser.add_argument('--max-size', type=int, default=10000, 
                       help='Maximum buffer size')
    parser.add_argument('--dry-run', action='store_true', 
                       help='Parse JSONL but do not insert into buffer')
    parser.add_argument('--max-lines', type=int, 
                       help='Maximum number of lines to process')
    parser.add_argument('--tz', help='IANA timezone for naive timestamps (e.g., Asia/Kolkata)')
    parser.add_argument('--map-severity', action='store_true',
                       help='Add numeric severity_num field for syslog events')
    parser.add_argument('--percent-as-ratio', action='store_true',
                       help='Add value_ratio field for SNMP metrics with unit=%%')
    
    args = parser.parse_args()
    
    # Handle stdin vs file input
    if args.stdin or args.jsonl_file == '-':
        if args.jsonl_file and args.jsonl_file != '-' and args.stdin:
            print("Error: Cannot specify both --stdin and a filename", file=sys.stderr)
            sys.exit(1)
        input_file = sys.stdin
        print("Reading from stdin...")
    else:
        if not args.jsonl_file:
            print("Error: Must specify input file or use --stdin", file=sys.stderr)
            parser.print_help()
            sys.exit(1)
        if not os.path.exists(args.jsonl_file):
            print(f"Error: JSONL file '{args.jsonl_file}' not found", file=sys.stderr)
            sys.exit(1)
        input_file = open(args.jsonl_file, 'r', encoding='utf-8')
    
    # Validate timezone if provided
    if args.tz:
        try:
            zoneinfo.ZoneInfo(args.tz)
        except zoneinfo.ZoneInfoNotFoundError:
            print(f"Error: Invalid timezone '{args.tz}'", file=sys.stderr)
            sys.exit(1)
    
    # Create buffer
    if args.use_memory:
        buffer = MessageBuffer(max_size=args.max_size, disk_buffer=False)
        print(f"Using in-memory buffer (max_size={args.max_size})")
    else:
        buffer = MessageBuffer(max_size=args.max_size, disk_buffer=True, 
                             disk_path=args.buffer_path)
        print(f"Using SQLite buffer at {args.buffer_path}")
    
    # Import JSONL data
    imported_count = 0
    error_count = 0
    
    try:
        for line_num, line in enumerate(input_file, 1):
            if args.max_lines and line_num > args.max_lines:
                print(f"Reached max lines limit ({args.max_lines})")
                break
            
            line = line.strip()
            if not line:
                continue
            
            try:
                event = json.loads(line)
                
                # Choose normalization function based on record type
                if args.record_type == 'snmp_metric':
                    message = normalize_snmp_metric(event, args.tz, args.percent_as_ratio)
                else:
                    message = normalize_syslog_event(event, args.tz, args.map_severity)
                
                if args.dry_run:
                    print(f"Line {line_num}: {json.dumps(message, indent=2)}")
                else:
                    if buffer.put(message):
                        imported_count += 1
                    else:
                        error_count += 1
                        print(f"Warning: Failed to add line {line_num} to buffer")
                
                if line_num % 100 == 0:
                    print(f"Processed {line_num} lines...")
                    
            except json.JSONDecodeError as e:
                error_count += 1
                print(f"Error parsing JSON on line {line_num}: {e}", file=sys.stderr)
            except Exception as e:
                error_count += 1
                print(f"Error processing line {line_num}: {e}", file=sys.stderr)
    
    except Exception as e:
        print(f"Error reading JSONL data: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        if input_file != sys.stdin:
            input_file.close()
    
    if not args.dry_run:
        stats = buffer.get_stats()
        print(f"\nImport completed:")
        print(f"  Successfully imported: {imported_count} messages")
        print(f"  Errors: {error_count}")
        print(f"  Buffer stats: {stats}")
    else:
        print(f"\nDry run completed:")
        print(f"  Would import: {imported_count} messages")
        print(f"  Errors: {error_count}")


if __name__ == '__main__':
    main()