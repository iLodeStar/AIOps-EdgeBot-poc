# EdgeBot - Edge Node Bot

A lightweight edge node data collector and shipper designed for Phase 1 AIOps deployment. EdgeBot collects logs and telemetry from multiple sources and streams them to a central mothership with minimal resource usage.

## Features

### Data Collection
- **Syslog Server**: RFC3164 and RFC5424 compliant syslog listener (UDP port 5514, TCP port 5515)
- **SNMP Polling**: Async SNMPv2c polling with OID name mapping
- **Weather Context**: Periodic weather data from Open-Meteo API
- **File Tailing**: Multi-file log tailing with rotation and glob pattern support
- **Network Flows**: NetFlow v5/v9/IPFIX and sFlow telemetry collection via UDP
- **NMEA Vessel Telemetry**: NMEA 0183 sentence parsing for vessel position, speed, and heading
- **Service Discovery**: Automatic detection of listening services and log files
- **File-based Import**: Tools to import CSV weather data and JSONL syslog events

### Data Shipping
- **Batched Streaming**: Configurable batch sizes and timeouts
- **Compression**: Gzip compression for reduced bandwidth
- **Authentication**: Bearer token support
- **Retry Logic**: Exponential backoff with disk buffering
- **Rate Limiting**: Token bucket rate limiting
- **File Output**: Support for file:// URLs to write payload files for testing

### Persistence & Buffering
- **SQLite Spool**: Optional SQLite-backed message buffer for persistence
- **Commit/ACK Support**: Messages are marked as completed or failed
- **Buffer Statistics**: Detailed stats on message throughput and status

### Security & Reliability
- **TLS Support**: HTTPS with optional mutual TLS
- **Non-root Execution**: Runs as unprivileged user by default
- **Self-healing**: Auto-restart failed components
- **Graceful Shutdown**: Signal handling for clean shutdown

### Observability
- **Health Endpoint**: `/healthz` for service status
- **Metrics Endpoint**: `/metrics` for Prometheus monitoring
- **Structured Logging**: JSON-formatted logs with multiple levels

## Quick Start

### Using Docker (Recommended)

1. **Build and run with Docker Compose:**
```bash
docker-compose up -d
```

2. **Check health:**
```bash
curl http://localhost:8081/healthz
```

3. **View metrics:**
```bash
curl http://localhost:8082/metrics
```

### Using Python Virtual Environment

1. **Create and activate virtual environment:**
```bash
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# or
venv\\Scripts\\activate   # Windows
```

2. **Install dependencies:**
```bash
pip install -r requirements.txt
```

3. **Run EdgeBot:**
```bash
python -m app.main --config config.yaml
```

### Binary Usage

For production deployments, you can use the pre-built EdgeBot binary:

1. **Download the binary:**
```bash
# From GitHub Releases
wget https://github.com/iLodeStar/AIOps-EdgeBot-poc/releases/latest/download/edgebot
chmod +x edgebot
```

2. **Run with default configuration:**
```bash
# Uses built-in Delhi weather coordinates
./edgebot --config config.example.yaml
```

3. **Run with custom configuration:**
```bash
./edgebot --config /path/to/your/config.yaml
```

4. **Override settings with environment variables:**
```bash
# Change weather location
EDGEBOT_WEATHER_CITY="San Francisco" ./edgebot

# Change coordinates directly  
EDGEBOT_WEATHER_LAT="40.7128" EDGEBOT_WEATHER_LON="-74.0060" ./edgebot

# Custom mothership URL and auth token
EDGEBOT_MOTHERSHIP_URL="https://your-mothership.com/ingest" \
EDGEBOT_AUTH_TOKEN="your-token" \
./edgebot --config config.example.yaml
```

**Security Note:** The binary runs as non-root by default. For privileged port binding (514/515), use Docker port mapping (host 514->container 5514) or consider `setcap` for the binary (optional):
```bash
# Optional: Allow binding to privileged ports without root
sudo setcap 'cap_net_bind_service=+ep' ./edgebot
```

## Configuration

EdgeBot uses a YAML configuration file with environment variable overrides:

```yaml
# Server Configuration
server:
  host: "0.0.0.0"
  port: 8080

# Input Sources
inputs:
  syslog:
    enabled: true
    udp_port: 5514
    tcp_port: 5515
  
  snmp:
    enabled: false
    targets: []
  
  weather:
    enabled: false
    city: "New York"  # or use latitude/longitude
  
  logs:
    enabled: false
    paths: []                         # Explicit file paths to tail
    globs: ["/var/log/nginx/*.log"]   # Glob patterns for file discovery
    from_beginning: false             # Start tailing from end of files
    scan_interval: 2                  # Seconds between file scans
  
  flows:
    enabled: false
    netflow_ports: [2055]             # NetFlow v5/v9 UDP ports
    ipfix_ports: [4739]               # IPFIX UDP ports 
    sflow_ports: [6343]               # sFlow UDP ports
  
  nmea:
    enabled: false
    mode: udp                         # udp, tcp, or serial
    bind_address: "0.0.0.0"
    udp_port: 10110                   # Standard NMEA UDP port
    tcp_port: 10110
  
  discovery:
    enabled: false
    interval: 300                     # Discovery interval in seconds
    auto_tail_logs: true              # Auto-register found logs with file tailer
    extra_logs: []                    # Additional log paths to check

# Output Configuration
output:
  mothership:
    url: "https://your-mothership:8443/ingest"
    auth_token: null  # Set via EDGEBOT_AUTH_TOKEN env var
    batch_size: 100
    batch_timeout: 5.0

# Buffer Configuration
buffer:
  max_size: 10000                    # Max messages in memory
  disk_buffer: false                 # Enable SQLite persistence
  disk_buffer_path: "/tmp/edgebot_buffer.db"
  disk_buffer_max_size: "100MB"
```

## Cruise-Ship Deployment

EdgeBot includes specialized inputs for maritime vessel operations, including vessel telemetry, network flow analysis, and automatic service discovery.

### NMEA Vessel Telemetry

EdgeBot can consume NMEA 0183 data streams to provide vessel position, speed, course, and heading information:

```yaml
inputs:
  nmea:
    enabled: true
    mode: udp                    # UDP listener (most common)
    udp_port: 10110             # Standard NMEA port
    bind_address: "0.0.0.0"
```

**Supported NMEA Sentences:**
- **GPRMC**: GPS position, speed, course, and validity
- **GPVTG**: Velocity made good (speed and course)
- **GPHDT**: True heading

**Sample NMEA Message:**
```
$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A
```

**Parsed Output:**
```json
{
  "type": "nmea",
  "sentence": "GPRMC", 
  "lat": 48.1173,
  "lon": 11.5167,
  "sog_kn": 22.4,
  "cog_deg": 84.4,
  "valid": true
}
```

### Network Flow Telemetry

Collect network flow data from onboard networking equipment:

```yaml
inputs:
  flows:
    enabled: true
    netflow_ports: [2055, 9995]     # NetFlow v5/v9 collectors
    ipfix_ports: [4739]             # IPFIX collector  
    sflow_ports: [6343]             # sFlow collector
```

**Phase 1 Implementation:**
- Protocol version detection (NetFlow v5/v9/v10, IPFIX, sFlow)
- Raw packet forwarding with metadata (source IP, size, version)
- Base64 payload encoding for detailed analysis upstream
- Configurable high ports (no root privileges required)

### File Tailing and Log Collection

Monitor log files from onboard services with automatic rotation handling:

```yaml
inputs:
  logs:
    enabled: true
    paths: 
      - "/var/log/nginx/access.log"
      - "/var/log/dnsmasq.log"
    globs:
      - "/var/log/nginx/*.log"
      - "/var/log/bind/*.log"
    from_beginning: false           # Start from end (don't replay history)
    scan_interval: 2                # Check for new files/rotations every 2s
```

**Features:**
- **Rotation Detection**: Uses inode tracking to detect log rotation
- **Service Labeling**: Automatically labels logs (web, dns, etc.) based on file paths
- **Multi-file Support**: Tail multiple files simultaneously
- **Glob Patterns**: Discover files dynamically using glob patterns

### Service Discovery

Automatically discover onboard services and register their log files:

```yaml
inputs:
  discovery:
    enabled: true
    interval: 300                   # Run discovery every 5 minutes
    auto_tail_logs: true            # Auto-add discovered logs to file tailer
    extra_logs:                     # Additional paths to check
      - "/opt/captive-portal/access.log"
      - "/var/log/radius/radius.log"
```

**Discovery Methods:**
- **Port Scanning**: Uses `ss -tulpn` to find listening services
- **Common Log Locations**: Checks standard paths for nginx, DNS, HTTP servers
- **Service Mapping**: Maps discovered services to their typical log files
- **Auto-Registration**: Can automatically register found logs with the file tailer

**Sample Discovery Output:**
```json
{
  "type": "host_service_inventory",
  "listeners": [
    {"proto": "tcp", "local": "0.0.0.0:80", "proc": "users:((\"nginx\",pid=1234))"},
    {"proto": "udp", "local": "0.0.0.0:53", "proc": "users:((\"dnsmasq\",pid=5678))"}
  ],
  "log_candidates": [
    "/var/log/nginx/access.log",
    "/var/log/dnsmasq.log"
  ]
}
```

### Maritime Integration Example

Complete configuration for a cruise ship deployment:

```yaml
inputs:
  # Core syslog collection
  syslog:
    enabled: true
    udp_port: 5514
    tcp_port: 5515

  # Vessel position and navigation
  nmea:
    enabled: true
    mode: udp
    udp_port: 10110

  # Network monitoring
  flows:
    enabled: true
    netflow_ports: [2055]
    sflow_ports: [6343]

  # Log collection with service discovery
  discovery:
    enabled: true
    interval: 300
    auto_tail_logs: true
    extra_logs:
      - "/var/log/radius/radius.log"
      - "/opt/captive-portal/*.log"

  logs:
    enabled: true
    globs:
      - "/var/log/nginx/*.log"
      - "/var/log/bind/*.log" 
      - "/var/log/dhcp/*.log"
    scan_interval: 5

  # Weather at current vessel position
  weather:
    enabled: true
    latitude: 25.7617    # Updated periodically from NMEA
    longitude: -80.1918
    interval: 1800       # Every 30 minutes
```

**Buffer Options:**
- `disk_buffer: true` enables SQLite-backed persistent storage
- Messages are automatically committed/acked on successful send
- Failed messages can be retried from persistent storage
- Use `file://` URLs for testing without external endpoints

### Environment Variables

Key environment variables for overriding configuration:

- `EDGEBOT_MOTHERSHIP_URL`: Mothership ingestion endpoint
- `EDGEBOT_AUTH_TOKEN`: Authentication token
- `EDGEBOT_LOG_LEVEL`: Logging level (DEBUG, INFO, WARNING, ERROR)
- `EDGEBOT_SYSLOG_UDP_PORT`: Syslog UDP port
- `EDGEBOT_WEATHER_CITY`: Weather location

## Testing Data Collection

### Testing Syslog Collection

Send test syslog messages:

```bash
# UDP syslog
echo "<34>Oct 11 22:14:15 mymachine su: 'su root' failed for lonvick on /dev/pts/8" | nc -u localhost 5514

# TCP syslog
echo "<165>1 2003-08-24T05:14:15.000003-07:00 192.0.2.1 myproc 8710 - - %% It's time to make the do-nuts." | nc localhost 5515
```

### Testing SNMP Collection

Enable SNMP in config and add targets:

```yaml
inputs:
  snmp:
    enabled: true
    targets:
      - host: "192.168.1.1"
        community: "public"
        interval: 60
        oids:
          - "1.3.6.1.2.1.1.3.0"  # sysUpTime
          - "1.3.6.1.2.1.1.5.0"  # sysName
```

### Testing Weather Collection

Enable weather collection:

```yaml
inputs:
  weather:
    enabled: true
    city: "San Francisco"
    interval: 3600
```

### Testing File Tailing

Enable file tailing to monitor log files:

```yaml
inputs:
  logs:
    enabled: true
    paths: ["/var/log/nginx/access.log"]
    from_beginning: true  # For testing, read from beginning
```

Generate test log entries:
```bash
# Create test log file
echo "$(date) - Test log entry" >> /var/log/test.log

# Tail with EdgeBot monitoring this file
```

### Testing Network Flow Collection

Enable flow collection and test with sample data:

```yaml
inputs:
  flows:
    enabled: true
    netflow_ports: [2055]
    sflow_ports: [6343]
```

Send test flow data:
```bash
# Send test NetFlow packet to port 2055
echo -e '\x00\x05\x00\x01\x12\x34\x56\x78' | nc -u localhost 2055

# Send test sFlow packet to port 6343  
echo -e '\x00\x00\x00\x05\x00\x00\x00\x01' | nc -u localhost 6343
```

### Testing NMEA Collection

Enable NMEA collection:

```yaml
inputs:
  nmea:
    enabled: true
    mode: udp
    udp_port: 10110
```

Send test NMEA sentences:
```bash
# Test GPRMC sentence (position, speed, course)
echo '$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A' | nc -u localhost 10110

# Test GPVTG sentence (speed and course)  
echo '$GPVTG,084.4,T,077.3,M,022.4,N,041.5,K*48' | nc -u localhost 10110

# Test GPHDT sentence (true heading)
echo '$GPHDT,084.4,T*23' | nc -u localhost 10110
```

### Testing Service Discovery

Enable service discovery:

```yaml
inputs:
  discovery:
    enabled: true
    interval: 60  # Run every minute for testing
    auto_tail_logs: true
```

The discovery service will automatically:
1. Scan for listening services using `ss -tulpn`
2. Check common log file locations
3. Register discovered logs with the file tailer
4. Emit service inventory messages

## Data Import and Export Tools

EdgeBot includes command-line tools for importing historical data and exporting payloads for testing.

### Importing Weather CSV Data

Import CSV files containing weather data into the message buffer:

```bash
# Basic import with SQLite persistence
python tools/import_weather_csv.py samples/weather_data.csv

# Import from stdin
cat samples/weather_data.csv | python tools/import_weather_csv.py --stdin

# Import with timezone conversion (naive timestamps as local time)
python tools/import_weather_csv.py --tz Asia/Kolkata samples/weather_data.csv

# Import to in-memory buffer
python tools/import_weather_csv.py --use-memory samples/weather_data.csv

# Dry run to preview import
python tools/import_weather_csv.py --dry-run samples/weather_data.csv
```

**New flags:**
- `--stdin` - Read from stdin instead of file
- `--tz TIMEZONE` - IANA timezone for naive timestamps (e.g., Asia/Kolkata)

Expected CSV columns:
- `timestamp`, `latitude`, `longitude`, `city`
- `temperature_celsius`, `humidity_percent`, `wind_speed_kmh`
- `wind_direction_degrees`, `pressure_hpa`, `weather_description`

### Importing JSONL Events (Syslog & SNMP)

Import JSONL files containing structured syslog events or SNMP metrics:

```bash
# Import syslog events with severity mapping
python tools/import_jsonl_events.py --record-type syslog_event --map-severity samples/syslog_events.jsonl

# Import SNMP metrics with percent-to-ratio conversion
python tools/import_jsonl_events.py --record-type snmp_metric --percent-as-ratio samples/snmp_metrics.jsonl

# Import from stdin with timezone conversion
cat samples/syslog_events.jsonl | python tools/import_jsonl_events.py --stdin --tz UTC

# Import first 100 events only
python tools/import_jsonl_events.py --max-lines 100 samples/syslog_events.jsonl

# Preview import format
python tools/import_jsonl_events.py --dry-run --max-lines 5 samples/syslog_events.jsonl
```

**New flags:**
- `--stdin` - Read from stdin instead of file
- `--record-type {syslog_event,snmp_metric}` - Type of records to import (default: syslog_event)
- `--tz TIMEZONE` - IANA timezone for naive timestamps
- `--map-severity` - Add numeric severity_num field for syslog events (RFC5424 mapping)
- `--percent-as-ratio` - Add value_ratio field for SNMP metrics with unit=%

**Syslog Event Fields:**
- `timestamp`, `host`, `message`
- `facility`, `severity`, `program`, `pid`
- Additional fields are preserved as `extra_*`

**SNMP Metric Fields:**
- `timestamp`, `host`, `oid`, `metric_name`
- `value`, `unit`, `interface`, `community`, `snmp_version`
- Additional fields are preserved as `extra_*`

**Severity Mapping (--map-severity):**
- emergency/emerg: 0, alert: 1, critical/crit: 2, error/err: 3
- warning/warn: 4, notice: 5, informational/info: 6, debug: 7

### Database Inspection

Inspect the SQLite message buffer:

```bash
# Show statistics and sample messages
python tools/db_dump.py /tmp/edgebot_buffer.db

# Show schema, stats, and 10 messages
python tools/db_dump.py /tmp/edgebot_buffer.db --all

# Show only pending messages
python tools/db_dump.py --messages 20 --status pending

# Clean up completed messages older than 1 day
python tools/db_dump.py --cleanup 86400
```

### File-based Payload Export

Export message buffer contents to payload files for testing:

```bash
# Ship to file directory
python tools/ship_spool_to_file.py \
  --output-dir /tmp/payloads \
  --batch-size 50 \
  --create-output-dir

# Files generated:
# payload-TIMESTAMP.json.gz  (compressed)
# payload-TIMESTAMP.json     (readable)
```

### Configuration for File Output

Configure EdgeBot to write payloads to files instead of HTTP:

```yaml
output:
  mothership:
    url: "file:///tmp/edgebot-output"  # Use file:// URL
    batch_size: 100
    compression: true
```

## Monitoring

### Health Check

The health endpoint provides service status:

```bash
curl http://localhost:8081/healthz
```

Response:
```json
{
  "status": "healthy",
  "timestamp": "2025-01-01T12:00:00Z",
  "services": {
    "syslog_server": {"healthy": true},
    "output_shipper": {"healthy": true}
  }
}
```

### Metrics

Prometheus-compatible metrics are available:

```bash
curl http://localhost:8082/metrics
```

Key metrics:
- `edgebot_output_shipper_total_messages_sent`
- `edgebot_output_shipper_total_batches_sent`
- `edgebot_syslog_server_running`

## Troubleshooting

### Common Issues

1. **Port binding errors**: Ensure ports 5514/5515 are not in use
2. **Permission denied**: Run as root for privileged ports or use non-privileged ports
3. **Connection refused**: Check mothership URL and network connectivity
4. **High memory usage**: Reduce buffer sizes in configuration

### Log Analysis

View structured logs:
```bash
docker logs edgebot | jq .
```

### Resource Usage

EdgeBot is designed for minimal resource usage:
- Memory: ~50-100MB typical
- CPU: <5% on modest hardware
- Network: Depends on data volume and batch settings

## Security Considerations

- Run as non-root user (default in Docker)
- Use TLS for mothership communication
- Secure authentication tokens
- Network isolation in production
- Regular security updates

## Development

### Running Tests

```bash
python -m pytest tests/
```

### Code Style

```bash
black app/
flake8 app/
```

### Contributing

1. Fork the repository
2. Create feature branch
3. Add tests for new functionality
4. Ensure all tests pass
5. Submit pull request

## License

Copyright 2025 iLodeStar

Licensed under the Apache License, Version 2.0. See LICENSE file for details.