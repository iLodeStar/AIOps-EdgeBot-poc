# EdgeBot Mothership - Centralized Data Processing Service

Phase 1.5 implementation of the AIOps EdgeBot mothership service, providing centralized data processing, enrichment, and ingestion capabilities with dual-sink support for TimescaleDB and Loki.

## Overview

The Mothership service receives data from EdgeBot instances, performs deterministic redaction and enrichment, optionally applies LLM-assisted enrichment (with strict guardrails), and stores the processed data in dual storage sinks: TimescaleDB (default) for analytics and Loki (optional) for log aggregation and search.

## Key Features

- **PII-Safe Processing Pipeline**: Deterministic redaction runs BEFORE any LLM processing
- **Multi-stage Enrichment**: Deterministic enrichment + optional AI-assisted enrichment  
- **Dual-Sink Storage**: TimescaleDB for structured analytics + Loki for log search
- **Circuit Breaker Protection**: LLM failures don't affect deterministic processing
- **Comprehensive Monitoring**: Health checks, metrics, and detailed statistics
- **Cloud-Native**: FastAPI service with async processing and connection pooling
- **Safe Loki Labeling**: Automatically avoids high-cardinality labels to prevent performance issues

## Architecture

```
┌─────────────┐    ┌──────────────────┐    ┌─────────────┐
│   EdgeBot   │───▶│    Mothership    │───▶│ TimescaleDB │
│  (Phase 1)  │    │   (Phase 1.5)    │    │ (Analytics) │
└─────────────┘    └──────────────────┘    └─────────────┘
                           │                         
                    ┌──────▼──────┐          ┌─────────────┐
                    │   Pipeline  │─────────▶│    Loki     │
                    │             │          │ (Log Search)│
                    │ 1. Redaction│          └─────────────┘
                    │ 2. Enrich   │                   │
                    │ 3. LLM (opt)│          ┌─────────────┐
                    │ 4. Dual-sink│─────────▶│   Grafana   │
                    └─────────────┘          │(Visualization)│
                                             └─────────────┘
```

### Key Features
- **Dual-sink writes**: TimescaleDB + Loki simultaneously
- **PII-Safe processing**: Redaction runs before any LLM processing
- **Safe Loki labeling**: Avoids high-cardinality issues
- **Batching & Retry**: Efficient processing with configurable timeouts
- **Circuit breaker protection**: LLM failures don't affect core pipeline
- **Comprehensive monitoring**: Health checks, metrics, structured logging
- **Flexible configuration**: Enable/disable sinks and features independently

## Processing Pipeline

The pipeline ensures **PII safety** by running redaction processors BEFORE any LLM processing:

### 1. Redaction Phase (Deterministic, Always Runs First)
- **Drop Fields**: Remove sensitive fields (`password`, `token`, `secret`, etc.)
- **Pattern Masking**: Mask sensitive patterns in text (SSNs, credit cards, etc.)
- **Field Hashing**: Hash PII fields for pseudonymization
- **Safety Validation**: Ensure PII is properly redacted before LLM

### 2. Enrichment Phase (Deterministic)
- **Add Tags**: Static tags for processing metadata
- **Severity Mapping**: String severities to numeric values
- **Service Extraction**: Extract service names from paths/hostnames  
- **Geo Hints**: Add geographical context based on IP ranges
- **Site/Environment Tags**: Extract deployment context
- **Timestamp Normalization**: Standardize timestamp formats

### 3. LLM Enhancement (Optional, Feature-Flagged OFF by default)
- **Guardrailed Processing**: Only redacted data sent to LLM
- **Confidence Thresholding**: Only apply high-confidence results (≥0.8)
- **Circuit Breaker**: Automatic fallback on failures
- **Bounded Context**: Limited prompt size and response tokens
- **Schema Validation**: Strict JSON schema for LLM responses

### 4. Dual-Sink Storage (Fanout to Multiple Storage Backends)
- **TimescaleDB Sink**: Structured data for SQL analytics and time-series analysis
- **Loki Sink** (Optional): Log aggregation with safe labeling strategy
- **Concurrent Writes**: All enabled sinks receive processed data simultaneously
- **Per-sink Error Handling**: Independent error handling and retry logic
- **Safe Labeling**: Automatic avoidance of high-cardinality labels in Loki
- **Batching & Timeouts**: Configurable batch processing for optimal performance

## Quick Start

### TimescaleDB Only (Default)
```bash
cd mothership
pip install -r requirements.txt
python -m app.server
```

### With Loki + Grafana (Dual-Sink)
```bash
# Start Loki + Grafana
docker-compose -f ../compose.observability.yml up -d

# Start mothership with Loki enabled
export LOKI_ENABLED=true
export LOKI_URL=http://localhost:3100
python -m app.server
```

### Docker Deployment

```bash
cd mothership
docker build -t mothership:1.5 .

# TimescaleDB only
docker run -p 8443:8443 \
  -e MOTHERSHIP_DB_DSN="postgresql://user:pass@host:5432/mothership" \
  mothership:1.5

# With dual-sink support (TimescaleDB + Loki)
docker run -p 8443:8443 \
  -e MOTHERSHIP_DB_DSN="postgresql://user:pass@host:5432/mothership" \
  -e LOKI_ENABLED=true \
  -e LOKI_URL=http://loki:3100 \
  mothership:1.5
```

### Testing

```bash
cd mothership
python -m tests.test_pipeline
python -m tests.test_llm  
python -m tests.test_server
python -m tests.test_loki_sink  # Loki integration tests
```

## Configuration

Configuration via YAML file (`config.yaml`) with environment variable overrides:

```yaml
server:
  host: "0.0.0.0"
  port: 8443

database:
  # Option 1: Full DSN
  dsn: "postgresql://mothership:pass@localhost:5432/mothership"
  
  # Option 2: Individual parameters
  host: "localhost"
  port: 5432
  database: "mothership"
  user: "mothership"
  password: "mothership"

pipeline:
  processors:
    redaction:
      enabled: true
      drop_fields: ["password", "secret", "token", "key"]
      mask_patterns:
        - "password=\\S+"
        - "\\b\\d{3}-\\d{2}-\\d{4}\\b"  # SSN pattern
      hash_fields: ["username", "email"]
      salt: "your-secret-salt"
    
    enrichment:
      enabled: true
      add_tags:
        processed_by: "mothership"
        version: "1.5"
      severity_mapping:
        emergency: 0
        alert: 1
        critical: 2
        error: 3
        warning: 4
        notice: 5
        info: 6
        debug: 7

llm:
  enabled: false  # Default OFF for safety
  endpoint: "https://api.openai.com/v1"
  model: "gpt-3.5-turbo"
  api_key: "${OPENAI_API_KEY}"
  confidence_threshold: 0.8
  max_tokens: 150
  temperature: 0.0
  circuit_breaker:
    enabled: true
    failure_threshold: 5
    reset_timeout: 60

# Dual-sink storage configuration
sinks:
  timescaledb:
    enabled: true  # Default enabled
  
  loki:
    enabled: false  # Default OFF, set LOKI_ENABLED=true to enable
    url: "http://localhost:3100"
    tenant_id: null  # Optional multi-tenancy
    username: null   # Optional basic auth
    password: null   # Optional basic auth
    batch_size: 100
    batch_timeout_seconds: 5.0
    max_retries: 3
    retry_backoff_seconds: 1.0
    timeout_seconds: 30.0
```

### Environment Variables

Key overrides:

**Core Settings:**
- `MOTHERSHIP_DB_DSN`: Database connection string
- `MOTHERSHIP_LLM_ENABLED`: Enable/disable LLM (true/false)
- `MOTHERSHIP_LLM_API_KEY`: OpenAI API key
- `MOTHERSHIP_LOG_LEVEL`: Logging level (DEBUG/INFO/WARNING/ERROR)

**Loki Sink Settings:**
- `LOKI_ENABLED`: Enable Loki sink (true/false, default: false)
- `LOKI_URL`: Loki API endpoint (default: http://localhost:3100)
- `LOKI_TENANT_ID`: Optional tenant ID for multi-tenant Loki
- `LOKI_USERNAME`: Basic auth username (optional)
- `LOKI_PASSWORD`: Basic auth password (optional)
- `LOKI_BATCH_SIZE`: Batch size for Loki writes (default: 100)
- `LOKI_BATCH_TIMEOUT_SECONDS`: Batch timeout (default: 5.0)

**Example Production Config:**
```bash
# Enable dual-sink mode
export LOKI_ENABLED=true
export LOKI_URL=https://loki.company.com
export LOKI_TENANT_ID=edgebot
export MOTHERSHIP_DB_DSN="postgresql://user:pass@host:5432/mothership"
```

## API Endpoints

### POST /ingest

Ingest events for processing:

```json
{
  "messages": [
    {
      "type": "syslog",
      "timestamp": "2025-01-01T00:00:00Z",
      "message": "User login successful",
      "source": "web01",
      "severity": "info"
    }
  ]
}
```

Response (with dual-sink support):
```json
{
  "status": "success",
  "processed_events": 1,
  "processing_time": 0.045,
  "sink_results": {
    "tsdb": {"written": 1, "errors": 0},
    "loki": {"written": 1, "errors": 0, "queued": 5}
  }
}
```

### GET /healthz

Health check endpoint (with dual-sink status):

```json
{
  "status": "healthy",
  "timestamp": "2025-01-01T00:00:00Z",
  "version": "1.5.0",
  "database": true,
  "sinks": {
    "tsdb": {"healthy": true, "enabled": true},
    "loki": {"healthy": true, "enabled": true}
  },
  "enabled_sinks": ["tsdb", "loki"],
  "pipeline_processors": ["DropFields", "AddTags", "SeverityMap", "LokiSink"]
}
```

### GET /metrics

Prometheus metrics endpoint returning metrics in Prometheus format.

### GET /stats

Detailed service statistics:

```json
{
  "service": {
    "uptime": 3600.5,
    "version": "1.5.0"
  },
  "pipeline": {
    "total_events": 1250,
    "successful_events": 1248,
    "processors": {
      "DropFields": {"processed": 1250, "errors": 0},
      "LLMEnricher": {"processed": 800, "confidence_threshold": 0.8}
    }
  },
  "database": {
    "total_inserts": 1248,
    "events_last_hour": 156
  }
}
```

## TimescaleDB Schema

### Events Table (Hypertable)

```sql
CREATE TABLE events (
    ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),  -- Event timestamp
    type TEXT NOT NULL,                      -- Event type (syslog, log, snmp, etc.)
    source TEXT NOT NULL,                    -- Source identifier
    data JSONB NOT NULL,                     -- Full event payload after processing
    id BIGSERIAL,                           -- Auto-increment ID
    created_at TIMESTAMPTZ DEFAULT NOW()     -- Insert timestamp
);

-- Create hypertable with 1-day chunks
SELECT create_hypertable('events', 'ts', chunk_time_interval => INTERVAL '1 day');

-- Indexes for efficient queries
CREATE INDEX idx_events_type_ts ON events (type, ts DESC);
CREATE INDEX idx_events_source_ts ON events (source, ts DESC);
CREATE INDEX idx_events_data_gin ON events USING GIN (data);
```

### Query Examples

```sql
-- Recent events by type
SELECT * FROM events WHERE type = 'syslog' AND ts > NOW() - INTERVAL '1 hour';

-- Events with specific tags
SELECT * FROM events WHERE data @> '{"tags": {"service": "nginx"}}';

-- Aggregated stats
SELECT type, COUNT(*), date_trunc('hour', ts) as hour
FROM events 
WHERE ts > NOW() - INTERVAL '24 hours'
GROUP BY type, hour
ORDER BY hour DESC;
```

## Safety Model

### PII Protection

1. **Deterministic Redaction First**: All PII redaction happens BEFORE any LLM processing
2. **Field Dropping**: Sensitive fields completely removed
3. **Pattern Masking**: Regex-based masking of sensitive patterns
4. **Field Hashing**: Cryptographic hashing with salt for pseudonymization
5. **Validation**: PII safety validator ensures redaction worked

### LLM Guardrails

1. **Feature Flag**: LLM disabled by default, must be explicitly enabled
2. **Pre-redacted Data**: LLM only sees data AFTER redaction pipeline
3. **Bounded Context**: Limited prompt size and response tokens
4. **Schema Validation**: Strict JSON schema for all LLM responses
5. **Confidence Gating**: Only apply results with confidence ≥ threshold
6. **Circuit Breaker**: Automatic fallback on errors or high failure rates
7. **No PII in Prompts**: Redacted data ensures no sensitive info sent to LLM

### Audit Trail

- Processing decisions logged with confidence scores
- Pipeline execution times tracked
- Error rates and circuit breaker states monitored
- Full request/response audit available via structured logging

## Monitoring

### Health Checks

- Database connectivity
- Pipeline processor status
- LLM circuit breaker state

### Metrics (Prometheus)

- `mothership_ingestion_requests_total` - Request counters by status
- `mothership_ingestion_events_total` - Total events processed
- `mothership_pipeline_duration_seconds` - Processing time distribution
- `mothership_database_writes_total` - Database write success/failure rates
- `mothership_active_connections` - Active database connections

### Logging

Structured JSON logging with:
- Request tracing
- Processing pipeline steps
- Error details and stack traces
- Performance metrics

## Deployment

### Production Checklist

- [ ] Set `MOTHERSHIP_DB_DSN` with production database
- [ ] Configure log level appropriately (`INFO` or `WARNING`)
- [ ] Set up TimescaleDB with proper sizing
- [ ] Configure redaction rules for your data
- [ ] If using LLM, set `MOTHERSHIP_LLM_API_KEY` and test thoroughly
- [ ] Set up monitoring and alerting
- [ ] Configure backup strategy for TimescaleDB

### Resource Requirements

- **CPU**: 2+ cores recommended
- **Memory**: 2GB+ (more for LLM processing)
- **Storage**: Depends on ingestion rate, plan for time-series growth
- **Network**: Async processing handles high ingestion rates efficiently

## Development

### Testing

```bash
# Run all tests
python -m tests.test_pipeline
python -m tests.test_llm
python -m tests.test_server

# Test with different configurations
MOTHERSHIP_LLM_ENABLED=true python -m tests.test_llm
```

### Code Structure

```
mothership/
├── app/
│   ├── server.py           # FastAPI application
│   ├── config.py           # Configuration management
│   ├── pipeline/           # Processing pipeline
│   │   ├── processor.py    # Base classes
│   │   ├── processors_redaction.py  # PII safety processors
│   │   ├── processors_enrich.py     # Deterministic enrichment
│   │   └── llm_enricher.py          # LLM enhancement
│   └── storage/
│       ├── tsdb.py         # TimescaleDB interface
│       ├── loki.py         # Loki client and batching
│       └── sinks.py        # Dual-sink manager
├── tests/                  # Comprehensive test suite
│   ├── test_loki_sink.py   # Loki integration tests
│   └── ...                 # Other test files
├── requirements.txt        # Dependencies
├── Dockerfile             # Container image
└── README.md              # This file
```

## Troubleshooting

### Loki Not Receiving Data
1. Check `LOKI_ENABLED=true` is set
2. Verify `LOKI_URL` is accessible: `curl http://localhost:3100/ready`
3. Check mothership logs for Loki errors
4. Validate Loki authentication if using `LOKI_USERNAME`/`LOKI_PASSWORD`

### High Memory Usage
1. Reduce `LOKI_BATCH_SIZE` for memory-constrained environments
2. Decrease `LOKI_BATCH_TIMEOUT_SECONDS` for faster batch flushes
3. Monitor sink health: `GET /healthz`
4. Check for high-cardinality labels in logs

### Performance Issues
1. Enable both sinks for load distribution
2. Increase batch sizes for higher throughput
3. Use multiple mothership instances behind load balancer
4. Monitor `processing_time` in responses for bottlenecks

### Safe Loki Labeling
The Loki sink automatically uses safe, low-cardinality labels:
- ✅ **Safe labels**: `type`, `service`, `host`, `site`, `env`, `severity`
- ❌ **Avoided labels**: `request_id`, `user_id`, `ip`, `timestamp`

For detailed Loki + Grafana setup, see `../docs/LOKI_GRAFANA_SETUP.md`.

## License

Licensed under the Apache License, Version 2.0. See LICENSE file for details.
