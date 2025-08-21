# AIOps-EdgeBot-poc

Phase 1 Edge Node Bot implementation for AIOps deployment. This repository contains a lightweight edge node data collector and shipper designed for minimal resource usage, near real-time streaming, and strong security/observability.

## Phase 1 Implementation

The EdgeBot is a lightweight data collector that:
- ✅ Collects logs from multiple sources (Syslog, SNMP, Weather API)
- ✅ Normalizes and labels data with type detection
- ✅ Streams data to mothership with batching and compression
- ✅ Provides security (TLS, auth tokens, non-root execution)
- ✅ Offers observability (health/metrics endpoints, structured logs)
- ✅ Ensures reliability (retries, buffering, self-healing)
- ✅ Easy deployment (Docker, virtual environment)

## Quick Start

### Using Docker
```bash
cd edge_node
docker-compose up -d
```

### Using Python
```bash
cd edge_node
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python -m app.main
```

## Project Structure

```
edge_node/                 # Main EdgeBot implementation
├── app/                  # Application code
│   ├── main.py          # Entry point with supervision
│   ├── config.py        # Configuration management
│   ├── inputs/          # Data collection modules
│   │   ├── syslog_server.py    # RFC3164/5424 syslog listener
│   │   ├── snmp_poll.py        # SNMP v2c polling
│   │   └── weather.py          # Open-Meteo weather API
│   └── output/          # Data shipping
│       └── shipper.py   # HTTPS streaming with batching
├── config.yaml          # Configuration file
├── requirements.txt     # Python dependencies
├── Dockerfile          # Container build
├── docker-compose.yaml # Easy deployment
└── README.md           # Detailed documentation
```

## Key Features

### Data Collection
- **Syslog Server**: Async UDP/TCP listener on ports 5514/5515
- **SNMP Polling**: Configurable targets with OID name mapping  
- **Weather Context**: Periodic weather data from Open-Meteo

### Data Shipping  
- **Batched Streaming**: Configurable batch sizes and timeouts
- **Compression**: Gzip compression for bandwidth efficiency
- **Authentication**: Bearer token support
- **Retry Logic**: Exponential backoff with buffering

### Observability
- **Health Endpoint**: `/healthz` for service monitoring
- **Metrics Endpoint**: `/metrics` for Prometheus
- **Structured Logging**: JSON logs with multiple levels

### Security & Reliability
- **Non-root Execution**: Secure by default
- **TLS Support**: HTTPS with optional mTLS
- **Self-healing**: Auto-restart failed components
- **Graceful Shutdown**: Signal handling

## Configuration

See `edge_node/config.yaml` for full configuration options and `edge_node/.env.example` for environment variables.

Key settings:
- Mothership URL and authentication
- Input source enablement (syslog/SNMP/weather)  
- Batch sizes and timeouts
- Security and TLS options

## Testing

Basic validation:
```bash
cd edge_node
python -m app.main --dry-run
python -m tests.test_basic
```

Send test syslog messages:
```bash
python send_test_syslog.py
```

## Next Phases

This Phase 1 implementation provides the foundation for:
- Phase 2: Enhanced data processing and local analytics
- Phase 3: Distributed intelligence and autonomous operations
- Phase 4: Full AIOps integration with predictive capabilities

## License

Licensed under the Apache License, Version 2.0. See LICENSE file for details.