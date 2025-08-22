# EdgeBot Mothership

The mothership is the data collection server that receives telemetry from EdgeBot nodes and stores it in dual sinks: TimescaleDB (default) and Loki (optional).

## Quick Start

### TimescaleDB Only (Default)
```bash
cd mothership
pip install -r requirements.txt
python main.py
```

### With Loki + Grafana
```bash
# Start Loki + Grafana
docker-compose -f ../compose.observability.yml up -d

# Start mothership with Loki enabled
export LOKI_ENABLED=true
export LOKI_URL=http://localhost:3100
python main.py
```

The server starts on `http://localhost:8080` by default.

## API Endpoints

### `POST /ingest`
Receives batched telemetry data from EdgeBot nodes.

**Request**: JSON payload with gzip compression support
```json
{
  "messages": [
    {
      "message": "Log message",
      "timestamp": 1640995200,
      "type": "syslog",
      "service": "edgebot",
      "host": "edge-01",
      "severity": "info"
    }
  ],
  "batch_size": 1,
  "timestamp": 1640995200,
  "source": "edge-01",
  "is_retry": false
}
```

**Response**: Per-sink write counts
```json
{
  "status": "success",
  "received": 1,
  "sanitized": 1,
  "written": 1,
  "errors": 0,
  "sink_results": {
    "tsdb": {"written": 1, "errors": 0},
    "loki": {"written": 1, "errors": 0, "queued": 0}
  }
}
```

### `GET /health`
Health check including sink status.

**Response**:
```json
{
  "status": "healthy",
  "timestamp": 1640995200,
  "healthy": true,
  "sinks": {
    "tsdb": {"healthy": true, "enabled": true},
    "loki": {"healthy": true, "enabled": true}
  },
  "enabled_sinks": ["tsdb", "loki"]
}
```

### `GET /`
Basic server information.

## Configuration

Configure via environment variables:

### Storage Sinks
```bash
# TimescaleDB (enabled by default)
export TSDB_ENABLED=true
export TSDB_HOST=localhost
export TSDB_PORT=5432
export TSDB_DATABASE=edgebot
export TSDB_USERNAME=edgebot
export TSDB_PASSWORD=edgebot

# Loki (disabled by default)  
export LOKI_ENABLED=true
export LOKI_URL=http://localhost:3100
export LOKI_TENANT_ID=edgebot
export LOKI_USERNAME=user
export LOKI_PASSWORD=pass
export LOKI_BATCH_SIZE=100
export LOKI_BATCH_TIMEOUT_SECONDS=5.0
```

### Server
```bash
export SERVER_HOST=0.0.0.0
export SERVER_PORT=8080
export LOG_LEVEL=INFO
export LOG_FORMAT=json  # or leave unset for console
export DEV_MODE=true    # enables auto-reload
```

## Storage Sinks

### TimescaleDB Sink
- **Purpose**: Structured data storage for analytics
- **Features**: SQL queries, aggregations, time-series analysis
- **Status**: Placeholder implementation (TODO: add actual PostgreSQL/TimescaleDB integration)

### Loki Sink
- **Purpose**: Log aggregation and search
- **Features**: Text search, Grafana integration, efficient log storage
- **Safe Labeling**: Automatically avoids high-cardinality labels
- **Batching**: Configurable batch sizes and timeouts

## Data Processing Pipeline

1. **Receive**: Accept POST requests from EdgeBot nodes at `/ingest`
2. **Parse**: Handle JSON payloads with optional gzip compression  
3. **Sanitize**: Remove internal fields (e.g., `__spool_id`)
4. **Fan-out**: Write to all enabled sinks concurrently
5. **Respond**: Return per-sink write counts and status

## Development

### Running Tests
```bash
pip install -r requirements.txt
python -m pytest tests/ -v
```

### Local Development with Hot Reload
```bash
export DEV_MODE=true
python main.py
```

### Testing with Sample Data
```bash
# Send test payload
curl -X POST http://localhost:8080/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"message": "Test log", "service": "test", "severity": "info"}
    ],
    "batch_size": 1,
    "source": "test"
  }'

# Check health
curl http://localhost:8080/health
```

## Integration with EdgeBot Nodes

EdgeBot nodes automatically send data to the mothership. Configure the edge node:

```yaml
# edge_node/config.yaml
output:
  mothership:
    url: "http://localhost:8080/ingest"
    auth_token: "your-token"  # Optional
    batch_size: 100
    batch_timeout: 5.0
```

## Production Deployment

### Docker
```bash
# Build image
docker build -t edgebot-mothership .

# Run with environment variables
docker run -d \
  -p 8080:8080 \
  -e LOKI_ENABLED=true \
  -e LOKI_URL=http://loki:3100 \
  -e TSDB_HOST=timescaledb \
  edgebot-mothership
```

### Docker Compose
```yaml
services:
  mothership:
    build: ./mothership
    ports:
      - "8080:8080"
    environment:
      - LOKI_ENABLED=true
      - LOKI_URL=http://loki:3100
      - TSDB_HOST=timescaledb
      - TSDB_DATABASE=edgebot
    depends_on:
      - loki
      - timescaledb
```

## Architecture

```
EdgeBot Nodes → [HTTP/HTTPS] → Mothership → TimescaleDB (SQL analytics)
                                    ↓
                                  Loki (Log search)
                                    ↓
                                 Grafana (Visualization)
```

### Key Features
- **Dual-sink writes**: TimescaleDB + Loki simultaneously
- **Safe labeling**: Avoids high-cardinality issues in Loki
- **Batching**: Efficient batch processing with configurable timeouts
- **Reliability**: Per-sink error handling and retry logic
- **Observability**: Health checks, structured logging, metrics
- **Flexibility**: Enable/disable sinks independently

## Troubleshooting

### Loki Not Receiving Data
1. Check `LOKI_ENABLED=true` is set
2. Verify `LOKI_URL` is accessible
3. Check mothership logs for Loki errors
4. Test Loki endpoint: `curl http://localhost:3100/ready`

### High Memory Usage
1. Reduce `LOKI_BATCH_SIZE`
2. Decrease `LOKI_BATCH_TIMEOUT_SECONDS`
3. Monitor sink health: `GET /health`

### Performance Issues
1. Enable both sinks for load distribution
2. Increase batch sizes for higher throughput
3. Use multiple mothership instances behind load balancer

For detailed Loki setup, see `../docs/LOKI_GRAFANA_SETUP.md`.