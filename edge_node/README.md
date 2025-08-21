# EdgeBot - Edge Node Bot

A lightweight edge node data collector and shipper designed for Phase 1 AIOps deployment. EdgeBot collects logs and telemetry from multiple sources and streams them to a central mothership with minimal resource usage.

## Features

### Data Collection
- **Syslog Server**: RFC3164 and RFC5424 compliant syslog listener (UDP port 5514, TCP port 5515)
- **SNMP Polling**: Async SNMPv2c polling with OID name mapping
- **Weather Context**: Periodic weather data from Open-Meteo API
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

## Data Import and Export Tools

EdgeBot includes command-line tools for importing historical data and exporting payloads for testing.

### Importing Weather CSV Data

Import CSV files containing weather data into the message buffer:

```bash
# Import CSV with SQLite persistence
python tools/import_weather_csv.py samples/weather_data.csv

# Import to in-memory buffer
python tools/import_weather_csv.py --use-memory samples/weather_data.csv

# Dry run to preview import
python tools/import_weather_csv.py --dry-run samples/weather_data.csv
```

Expected CSV columns:
- `timestamp`, `latitude`, `longitude`, `city`
- `temperature_celsius`, `humidity_percent`, `wind_speed_kmh`
- `wind_direction_degrees`, `pressure_hpa`, `weather_description`

### Importing JSONL Syslog Events

Import JSONL files containing structured syslog events:

```bash
# Import all events
python tools/import_jsonl_events.py samples/syslog_events.jsonl

# Import first 100 events only
python tools/import_jsonl_events.py --max-lines 100 samples/syslog_events.jsonl

# Preview import format
python tools/import_jsonl_events.py --dry-run --max-lines 5 samples/syslog_events.jsonl
```

Expected JSONL fields:
- `timestamp`, `host`, `message`
- `facility`, `severity`, `program`, `pid`
- Additional fields are preserved as `extra_*`

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