# EdgeBot - Edge Node Bot

A lightweight edge node data collector and shipper designed for Phase 1 AIOps deployment. EdgeBot collects logs and telemetry from multiple sources and streams them to a central mothership with minimal resource usage.

## Features

### Data Collection
- **Syslog Server**: RFC3164 and RFC5424 compliant syslog listener (UDP port 5514, TCP port 5515)
- **SNMP Polling**: Async SNMPv2c polling with OID name mapping
- **Weather Context**: Periodic weather data from Open-Meteo API

### Data Shipping
- **Batched Streaming**: Configurable batch sizes and timeouts
- **Compression**: Gzip compression for reduced bandwidth
- **Authentication**: Bearer token support
- **Retry Logic**: Exponential backoff with disk buffering
- **Rate Limiting**: Token bucket rate limiting

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
```

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