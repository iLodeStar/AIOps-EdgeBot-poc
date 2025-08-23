# Loki + Grafana Setup Guide

This guide explains how to set up Loki as an optional log sink alongside TimescaleDB, and use Grafana for log visualization. This complements the full observability stack covered in [OBSERVABILITY.md](OBSERVABILITY.md).

## Overview

EdgeBot now provides a complete observability stack including:
- **Prometheus**: Metrics collection and alerting
- **Loki**: Log aggregation and search
- **Grafana**: Unified visualization for metrics and logs  
- **Alertmanager**: Alert routing and notifications

**See [OBSERVABILITY.md](OBSERVABILITY.md) for the complete setup guide including Prometheus metrics and alerting.**

## When to Use Loki

Loki is ideal for:
- **Log aggregation** from multiple EdgeBot nodes
- **Text-based searches** across log messages  
- **Time-series log visualization** in Grafana
- **Low-cost log storage** with automatic compression
- **Cloud-native deployments** with Kubernetes

Use Loki when you need:
- Fast text searches across logs
- Log correlation with metrics in Grafana
- Cost-effective long-term log retention
- Cloud-native log aggregation

Continue using TimescaleDB when you need:
- Complex analytical queries on structured data
- High-performance aggregations
- Precise time-series analysis
- SQL-based reporting

## Architecture

```
EdgeBot Nodes → Mothership → TimescaleDB (default)
                     ↓            ↓
                   Loki        Prometheus
                 (optional)        ↓
                     ↓         Alertmanager
                  Grafana ←────────┘
```

The mothership writes to multiple destinations:
- **TimescaleDB**: Structured data for analytics (default ON)
- **Loki**: Log streams for search and visualization (default OFF)
- **Prometheus**: Metrics for monitoring and alerting

## Safe Labeling Strategy

Loki uses labels to index log streams. **High cardinality labels cause performance issues**. The mothership implementation uses safe labeling:

### Safe Labels (Low Cardinality)
These labels are automatically extracted and indexed:
- `type` - Log/metric type (e.g., `application`, `system`) 
- `service` - Service name (e.g., `edgebot`, `auth`)
- `host` - Host/node identifier (e.g., `edge-01`)
- `site` - Site/location (e.g., `datacenter-a`)
- `env` - Environment (e.g., `prod`, `test`)
- `severity` - Log level (e.g., `error`, `warn`, `info`)
- `source` - Data source (e.g., `mothership`, `syslog`)

### Avoided Labels (High Cardinality)
These fields are stored in log content, not labels:
- `request_id`, `session_id`, `trace_id` - Unique identifiers
- `ip`, `user_id` - User-specific data
- `timestamp`, `filename`, `line` - Highly variable data
- `pid`, `thread_id` - Process-specific data

This ensures Loki performance remains optimal even with high log volumes.

## Enabling Loki

### Quick Start with Full Observability Stack

The easiest way is to use the full observability stack:

```bash
# Start complete stack (Prometheus, Loki, Grafana, Alertmanager)
docker-compose -f compose.observability.yml up -d

# Start mothership with Loki enabled (optional)
export LOKI_ENABLED=true
export LOKI_URL=http://localhost:3100
cd mothership
python -m app.server

# Access services:
# - Grafana: http://localhost:3000 (admin/admin)
# - Prometheus: http://localhost:9090
# - Alertmanager: http://localhost:9093
```

### Environment Variables

Set these environment variables to enable Loki:

```bash
# Enable Loki sink (disabled by default)
export LOKI_ENABLED=true

# Loki server URL
export LOKI_URL=http://localhost:3100

# Optional: Multi-tenancy
export LOKI_TENANT_ID=edgebot

# Optional: Authentication
export LOKI_USERNAME=your-username
export LOKI_PASSWORD=your-password

# Optional: Performance tuning
export LOKI_BATCH_SIZE=100
export LOKI_BATCH_TIMEOUT_SECONDS=5.0
export LOKI_MAX_RETRIES=3

# TimescaleDB is enabled by default
# export TSDB_ENABLED=true
```

### Defaults
- `TSDB_ENABLED=true` (TimescaleDB enabled by default)
- `LOKI_ENABLED=false` (Loki disabled by default)

### Production Deployment

For production, configure:

1. **Persistent Storage**: Configure Loki with object storage (S3, GCS)
2. **Authentication**: Set up proper auth tokens
3. **Retention**: Configure log retention policies
4. **Monitoring**: Add Loki and Grafana monitoring

Example production config:
```yaml
# docker-compose.prod.yml
services:
  mothership:
    environment:
      - LOKI_ENABLED=true
      - LOKI_URL=https://loki.your-domain.com
      - LOKI_USERNAME=edgebot
      - LOKI_PASSWORD_FILE=/run/secrets/loki_password
      - TSDB_ENABLED=true
    secrets:
      - loki_password
```

## Metrics Integration

The mothership now exposes comprehensive Prometheus metrics including:

### Loki-Specific Metrics
- `mship_sink_written_total{sink="loki"}` - Events written to Loki
- `mship_sink_write_seconds{sink="loki"}` - Loki write latency
- `mship_loki_queue_size` - Current Loki batch queue size

### General Metrics
- `mship_ingest_events_total` - Total events ingested
- `mship_written_events_total` - Total events written to all sinks
- `mship_ingest_seconds` - Ingestion latency
- `mship_pipeline_seconds` - Processing latency

**See [OBSERVABILITY.md](OBSERVABILITY.md#metrics) for the complete metrics reference.**

## LogQL Queries

Use these LogQL queries in Grafana to explore your EdgeBot data:

### Basic Log Filtering
```logql
# All logs from a specific service
{service="edgebot"}

# Error logs only
{service="edgebot", severity="error"}

# Logs from specific host
{host="edge-node-01"}

# Multiple services
{service=~"edgebot|auth|api"}
```

### Text Searches
```logql
# Search for specific text
{service="edgebot"} |= "connection failed"

# Case-insensitive search
{service="edgebot"} |~ `(?i)error`

# Exclude debug messages
{service="edgebot"} != "debug"

# JSON field extraction
{service="edgebot"} | json | user_id != ""
```

### Aggregations and Metrics
```logql
# Count logs per service
sum by (service) (count_over_time({service=~".*"}[5m]))

# Error rate
sum by (service) (rate({service="edgebot", severity="error"}[5m]))

# Top error messages
topk(10, sum by (message) (count_over_time({severity="error"}[1h])))

# Response time percentiles (from JSON logs)
quantile_over_time(0.95, {service="api"} | json | unwrap response_time [5m])
```

### Time Range Queries
```logql
# Last 1 hour
{service="edgebot"}[1h]

# Specific time range with rate
rate({service="edgebot"}[5m])

# Logs around specific time
{service="edgebot"} @ 1640995200
```

## Grafana Dashboard Setup

### Pre-provisioned Dashboards
The full observability stack includes pre-configured:
1. **Datasources**: Prometheus (default) and Loki
2. **Dashboard**: "EdgeBot Observability" with metrics and logs
3. **Variables**: Service and environment filtering

### Custom Dashboard Creation

**Log Volume Panel**:
- Query: `sum(rate({service=~".*"}[5m]))`
- Visualization: Time Series

**Log Stream Panel**:  
- Query: `{service="edgebot"} |= ""`
- Visualization: Logs

**Error Rate Panel**:
- Query: `sum by (service) (rate({severity="error"}[5m]))`
- Visualization: Stat

**Top Services Panel**:
- Query: `topk(10, sum by (service) (count_over_time({service=~".*"}[1h])))`
- Visualization: Bar Chart

### Alerts

Prometheus alerting includes Loki-specific rules:
```yaml
# No Loki writes despite queued events
- alert: LokiWritesZero
  expr: increase(mship_sink_written_total{sink="loki"}[10m]) == 0 and on() mship_loki_queue_size > 0
  for: 0m
```

**See [OBSERVABILITY.md](OBSERVABILITY.md#alerts) for complete alerting configuration.**

## Troubleshooting

### Loki Not Receiving Logs

1. **Check mothership logs**:
```bash
# Enable debug logging
export LOG_LEVEL=DEBUG
python -m mothership.app.server
```

2. **Check metrics**:
```bash
# Check if Loki sink is writing
curl http://localhost:8080/metrics | grep mship_sink_written_total

# Check Loki queue size
curl http://localhost:8080/metrics | grep mship_loki_queue_size
```

3. **Verify Loki endpoint**:
```bash
curl -X POST http://localhost:3100/loki/api/v1/push \
  -H "Content-Type: application/json" \
  -d '{"streams":[{"stream":{"service":"test"},"values":[["1640995200000000000","test message"]]}]}'
```

4. **Check sink health**:
```bash
curl http://localhost:8080/health
```

### High Cardinality Warnings

If Loki shows cardinality warnings:
1. Review labels in mothership logs
2. Ensure only safe labels are used
3. Move unique values to log content, not labels

### Performance Issues

For high-volume deployments:
1. **Increase batch size**: `LOKI_BATCH_SIZE=1000`
2. **Reduce retention**: Configure Loki compactor
3. **Use parallel uploads**: Deploy multiple mothership instances
4. **Optimize labels**: Minimize label count and values
5. **Monitor metrics**: Use Prometheus alerts for queue depth

### Missing Data

Check:
1. **Environment**: Ensure `LOKI_ENABLED=true`
2. **Metrics**: Check `mship_sink_written_total{sink="loki"}`
3. **Connectivity**: Network between mothership and Loki
4. **Authentication**: Credentials if auth is enabled
5. **Alerting**: Review LokiWritesZero alert

## Production Best Practices

1. **Storage**: Use object storage (S3/GCS) for chunks
2. **Scaling**: Use Loki in microservices mode for high volume
3. **Retention**: Set appropriate retention policies
4. **Monitoring**: Monitor Loki components and disk usage
5. **Security**: Use TLS and proper authentication
6. **Backup**: Regular backups of Loki index
7. **Alerting**: Use Prometheus alerts for Loki health

## Integration with EdgeBot

EdgeBot nodes automatically send data to the mothership `/ingest` endpoint. The mothership:

1. **Receives** batched events from EdgeBot nodes
2. **Processes** events through the pipeline (redaction, enrichment)
3. **Observes** metrics for ingestion, processing, and sink latencies
4. **Fans out** writes to enabled sinks (TSDB + Loki)
5. **Updates** per-sink metrics for monitoring
6. **Returns** per-sink write counts in response

Example EdgeBot configuration:
```yaml
# edge_node/config.yaml
output:
  mothership:
    url: "https://your-mothership:8080/ingest"
    auth_token: "your-token"
```

This setup provides seamless dual-sink operation with full observability and no changes required on EdgeBot nodes.

## Related Documentation

- [OBSERVABILITY.md](OBSERVABILITY.md) - Complete observability stack setup
- [Prometheus Metrics Reference](OBSERVABILITY.md#metrics)
- [Alert Configuration](OBSERVABILITY.md#alerts)
- [Troubleshooting Guide](OBSERVABILITY.md#troubleshooting)

## Safe Labeling Strategy

Loki uses labels to index log streams. **High cardinality labels cause performance issues**. The mothership implementation uses safe labeling:

### Safe Labels (Low Cardinality)
These labels are automatically extracted and indexed:
- `type` - Log/metric type (e.g., `application`, `system`) 
- `service` - Service name (e.g., `edgebot`, `auth`)
- `host` - Host/node identifier (e.g., `edge-01`)
- `site` - Site/location (e.g., `datacenter-a`)
- `env` - Environment (e.g., `prod`, `test`)
- `severity` - Log level (e.g., `error`, `warn`, `info`)
- `source` - Data source (e.g., `mothership`, `syslog`)

### Avoided Labels (High Cardinality)
These fields are stored in log content, not labels:
- `request_id`, `session_id`, `trace_id` - Unique identifiers
- `ip`, `user_id` - User-specific data
- `timestamp`, `filename`, `line` - Highly variable data
- `pid`, `thread_id` - Process-specific data

This ensures Loki performance remains optimal even with high log volumes.

## Enabling Loki

### Environment Variables

Set these environment variables to enable Loki:

```bash
# Enable Loki sink (disabled by default)
export LOKI_ENABLED=true

# Loki server URL
export LOKI_URL=http://localhost:3100

# Optional: Multi-tenancy
export LOKI_TENANT_ID=edgebot

# Optional: Authentication
export LOKI_USERNAME=your-username
export LOKI_PASSWORD=your-password

# Optional: Performance tuning
export LOKI_BATCH_SIZE=100
export LOKI_BATCH_TIMEOUT_SECONDS=5.0
export LOKI_MAX_RETRIES=3
```

### Docker Compose

Use the provided `compose.observability.yml` for local development:

```bash
# Start Loki + Grafana
docker-compose -f compose.observability.yml up -d

# Start mothership with Loki enabled
export LOKI_ENABLED=true
export LOKI_URL=http://localhost:3100
cd mothership
python -m app.server
```

### Production Deployment

For production, configure:

1. **Persistent Storage**: Configure Loki with object storage (S3, GCS)
2. **Authentication**: Set up proper auth tokens
3. **Retention**: Configure log retention policies
4. **Monitoring**: Add Loki and Grafana monitoring

Example production config:
```yaml
# docker-compose.prod.yml
services:
  mothership:
    environment:
      - LOKI_ENABLED=true
      - LOKI_URL=https://loki.your-domain.com
      - LOKI_USERNAME=edgebot
      - LOKI_PASSWORD_FILE=/run/secrets/loki_password
    secrets:
      - loki_password
```

## LogQL Queries

Use these LogQL queries in Grafana to explore your EdgeBot data:

### Basic Log Filtering
```logql
# All logs from a specific service
{service="edgebot"}

# Error logs only
{service="edgebot", severity="error"}

# Logs from specific host
{host="edge-node-01"}

# Multiple services
{service=~"edgebot|auth|api"}
```

### Text Searches
```logql
# Search for specific text
{service="edgebot"} |= "connection failed"

# Case-insensitive search
{service="edgebot"} |~ `(?i)error`

# Exclude debug messages
{service="edgebot"} != "debug"

# JSON field extraction
{service="edgebot"} | json | user_id != ""
```

### Aggregations and Metrics
```logql
# Count logs per service
sum by (service) (count_over_time({service=~".*"}[5m]))

# Error rate
sum by (service) (rate({service="edgebot", severity="error"}[5m]))

# Top error messages
topk(10, sum by (message) (count_over_time({severity="error"}[1h])))

# Response time percentiles (from JSON logs)
quantile_over_time(0.95, {service="api"} | json | unwrap response_time [5m])
```

### Time Range Queries
```logql
# Last 1 hour
{service="edgebot"}[1h]

# Specific time range with rate
rate({service="edgebot"}[5m])

# Logs around specific time
{service="edgebot"} @ 1640995200
```

## Grafana Dashboard Setup

### 1. Add Loki Data Source

In Grafana:
1. Go to Configuration → Data Sources
2. Add new Data Source → Loki
3. Set URL: `http://loki:3100` (or your Loki URL)
4. Configure authentication if needed
5. Test & Save

### 2. Create Log Dashboard

Example dashboard panels:

**Log Volume Panel**:
- Query: `sum(rate({service=~".*"}[5m]))`
- Visualization: Time Series

**Log Stream Panel**:  
- Query: `{service="edgebot"} |= ""`
- Visualization: Logs

**Error Rate Panel**:
- Query: `sum by (service) (rate({severity="error"}[5m]))`
- Visualization: Stat

**Top Services Panel**:
- Query: `topk(10, sum by (service) (count_over_time({service=~".*"}[1h])))`
- Visualization: Bar Chart

### 3. Alerts

Set up alerts for:
```logql
# High error rate
sum by (service) (rate({severity="error"}[5m])) > 0.1

# Service down (no logs)
absent_over_time({service="edgebot"}[10m])

# Specific error patterns
count_over_time({service="edgebot"} |= "connection refused"[5m]) > 5
```

## Troubleshooting

### Loki Not Receiving Logs

1. **Check mothership logs**:
```bash
# Enable debug logging
export LOG_LEVEL=DEBUG
python -m mothership.app.server
```

2. **Verify Loki endpoint**:
```bash
curl -X POST http://localhost:3100/loki/api/v1/push \
  -H "Content-Type: application/json" \
  -d '{"streams":[{"stream":{"service":"test"},"values":[["1640995200000000000","test message"]]}]}'
```

3. **Check sink health**:
```bash
curl http://localhost:8080/health
```

### High Cardinality Warnings

If Loki shows cardinality warnings:
1. Review labels in mothership logs
2. Ensure only safe labels are used
3. Move unique values to log content, not labels

### Performance Issues

For high-volume deployments:
1. **Increase batch size**: `LOKI_BATCH_SIZE=1000`
2. **Reduce retention**: Configure Loki compactor
3. **Use parallel uploads**: Deploy multiple mothership instances
4. **Optimize labels**: Minimize label count and values

### Missing Data

Check:
1. Mothership sink health: `/health` endpoint
2. Loki ingester status: `http://loki:3100/metrics`
3. Network connectivity between mothership and Loki
4. Authentication credentials

## Production Best Practices

1. **Storage**: Use object storage (S3/GCS) for chunks
2. **Scaling**: Use Loki in microservices mode for high volume
3. **Retention**: Set appropriate retention policies
4. **Monitoring**: Monitor Loki components and disk usage
5. **Security**: Use TLS and proper authentication
6. **Backup**: Regular backups of Loki index

## Integration with EdgeBot

EdgeBot nodes automatically send data to the mothership `/ingest` endpoint. The mothership:

1. **Receives** batched events from EdgeBot nodes
2. **Sanitizes** events (removes internal fields like `__spool_id`)
3. **Fans out** writes to enabled sinks (TSDB + Loki)
4. **Returns** per-sink write counts in response

Example EdgeBot configuration:
```yaml
# edge_node/config.yaml
output:
  mothership:
    url: "https://your-mothership:8080/ingest"
    auth_token: "your-token"
```

This setup provides seamless dual-sink operation with no changes required on EdgeBot nodes.