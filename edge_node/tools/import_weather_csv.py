#!/usr/bin/env python3
"""Import weather CSV data into the EdgeBot message buffer."""

import sys
import os
import csv
import argparse
import asyncio
from datetime import datetime, timezone
from typing import Dict, Any

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.output.shipper import MessageBuffer


def parse_csv_row(row: Dict[str, str]) -> Dict[str, Any]:
    """Parse a CSV row into a normalized weather message."""
    # Try to parse timestamp in various formats
    timestamp_str = row.get('timestamp', row.get('time', row.get('datetime')))
    if timestamp_str:
        try:
            # Try ISO format first
            if 'T' in timestamp_str:
                timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
            else:
                # Try common formats
                for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d']:
                    try:
                        timestamp = datetime.strptime(timestamp_str, fmt)
                        timestamp = timestamp.replace(tzinfo=timezone.utc)
                        break
                    except ValueError:
                        continue
                else:
                    timestamp = datetime.now(timezone.utc)
        except ValueError:
            timestamp = datetime.now(timezone.utc)
    else:
        timestamp = datetime.now(timezone.utc)
    
    # Extract weather data fields
    message = {
        'timestamp': timestamp.isoformat(),
        'type': 'weather',
        'source': 'csv-import',
        'location': {
            'latitude': float(row.get('latitude', row.get('lat', 0.0))),
            'longitude': float(row.get('longitude', row.get('lon', 0.0))),
            'city': row.get('city', row.get('location', 'unknown'))
        },
        'current_weather': {}
    }
    
    # Map common weather fields
    field_mappings = {
        'temperature': ['temperature_celsius', 'temp', 'temperature_c'],
        'temperature_celsius': ['temperature_celsius', 'temp_c', 'temp'],
        'humidity_percent': ['humidity_percent', 'humidity', 'rh'],
        'wind_speed_kmh': ['wind_speed_kmh', 'wind_speed', 'windspeed'],
        'wind_direction_degrees': ['wind_direction_degrees', 'wind_dir', 'wind_direction'],
        'pressure_hpa': ['pressure_hpa', 'pressure', 'sea_level_pressure'],
        'weather_code': ['weather_code', 'code', 'condition_code'],
        'weather_description': ['weather_description', 'description', 'condition']
    }
    
    for field, possible_keys in field_mappings.items():
        for key in possible_keys:
            if key in row and row[key]:
                try:
                    # Try to convert to float for numeric fields
                    if field in ['temperature_celsius', 'humidity_percent', 'wind_speed_kmh', 
                               'wind_direction_degrees', 'pressure_hpa', 'weather_code']:
                        message['current_weather'][field] = float(row[key])
                    else:
                        message['current_weather'][field] = row[key]
                    break
                except (ValueError, TypeError):
                    # Keep as string if conversion fails
                    message['current_weather'][field] = row[key]
                    break
    
    # Add any additional fields not mapped above
    for key, value in row.items():
        if (key not in ['timestamp', 'time', 'datetime', 'latitude', 'lat', 
                       'longitude', 'lon', 'city', 'location'] and 
            key not in [k for keys in field_mappings.values() for k in keys]):
            try:
                message['current_weather'][key] = float(value)
            except (ValueError, TypeError):
                message['current_weather'][key] = value
    
    return message


def main():
    """Main function."""
    parser = argparse.ArgumentParser(description='Import weather CSV data into EdgeBot buffer')
    parser.add_argument('csv_file', help='Path to the CSV file to import')
    parser.add_argument('--buffer-path', help='Path to SQLite buffer database', 
                       default='/tmp/edgebot_buffer.db')
    parser.add_argument('--use-memory', action='store_true', 
                       help='Use in-memory buffer instead of SQLite')
    parser.add_argument('--max-size', type=int, default=10000, 
                       help='Maximum buffer size')
    parser.add_argument('--dry-run', action='store_true', 
                       help='Parse CSV but do not insert into buffer')
    
    args = parser.parse_args()
    
    if not os.path.exists(args.csv_file):
        print(f"Error: CSV file '{args.csv_file}' not found", file=sys.stderr)
        sys.exit(1)
    
    # Create buffer
    if args.use_memory:
        buffer = MessageBuffer(max_size=args.max_size, disk_buffer=False)
        print(f"Using in-memory buffer (max_size={args.max_size})")
    else:
        buffer = MessageBuffer(max_size=args.max_size, disk_buffer=True, 
                             disk_path=args.buffer_path)
        print(f"Using SQLite buffer at {args.buffer_path}")
    
    # Import CSV data
    imported_count = 0
    error_count = 0
    
    try:
        with open(args.csv_file, 'r', encoding='utf-8') as f:
            # Detect delimiter
            sample = f.read(1024)
            f.seek(0)
            sniffer = csv.Sniffer()
            delimiter = sniffer.sniff(sample).delimiter
            
            reader = csv.DictReader(f, delimiter=delimiter)
            
            for row_num, row in enumerate(reader, 1):
                try:
                    message = parse_csv_row(row)
                    
                    if args.dry_run:
                        print(f"Row {row_num}: {message}")
                    else:
                        if buffer.put(message):
                            imported_count += 1
                        else:
                            error_count += 1
                            print(f"Warning: Failed to add row {row_num} to buffer")
                    
                    if row_num % 100 == 0:
                        print(f"Processed {row_num} rows...")
                        
                except Exception as e:
                    error_count += 1
                    print(f"Error processing row {row_num}: {e}", file=sys.stderr)
    
    except Exception as e:
        print(f"Error reading CSV file: {e}", file=sys.stderr)
        sys.exit(1)
    
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