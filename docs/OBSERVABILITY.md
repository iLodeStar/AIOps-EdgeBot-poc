# EdgeBot Observability Guide

This guide covers the complete observability stack for EdgeBot, including Prometheus metrics, Loki logs, Grafana dashboards, and alerting through Alertmanager.

## Quick Start

### 1. Start the Observability Stack

```bash
# Start all services (Prometheus, Alertmanager, Grafana, Loki)
docker-compose -f compose.observability.yml up -d

# Check that all services are healthy
docker-compose -f compose.observability.yml ps
```

### 2. Access the Services

| Service | URL | Credentials |
|---------|-----|-------------|
| **Grafana** | http://localhost:3000 | admin/admin |
| **Prometheus** | http://localhost:9090 | None |
| **Alertmanager** | http://localhost:9093 | None |
| **Loki** | http://localhost:3100 | None |

### 3. Start the Mothership

```bash
cd mothership

# With TimescaleDB only (default)
python -m app.server

# With both TimescaleDB and Loki  
export LOKI_ENABLED=true
export LOKI_URL=http://localhost:3100
python -m app.server

# Check metrics are being exposed
curl http://localhost:8080/metrics
```

### 4. View the Dashboard

1. Open Grafana at http://localhost:3000 (admin/admin)
2. Navigate to "Dashboards" → "Browse"  
3. Open "EdgeBot Observability" dashboard
4. Start sending events to see data populate

## Architecture

```
┌─────────────┐    ┌──────────────┐    ┌─────────────┐
│  Mothership │───▶│  Prometheus  │───▶│ Alertmanager│
│   :8080     │    │    :9090     │    │    :9093    │
└─────────────┘    └──────────────┘    └─────────────┘
       │                   │                   │
       │                   ▼                   ▼
       │           ┌─────────────┐    ┌─────────────┐
       └──────────▶│   Grafana   │    │    Slack    │
                   │    :3000    │    │  (optional) │
                   └─────────────┘    └─────────────┘
                           │
                           ▼
                   ┌─────────────┐
                   │    Loki     │
                   │    :3100    │
                   └─────────────┘
```

## Metrics

The mothership exposes the following metrics at `/metrics`:

### Counters

| Metric | Description | Labels |
|--------|-------------|---------|
| `mship_ingest_batches_total` | Total ingestion batches processed | None |
| `mship_ingest_events_total` | Total events ingested | None |
| `mship_written_events_total` | Total events written to all sinks | None |
| `mship_sink_written_total` | Total events written per sink | `sink` |
| `mship_requests_total` | Total HTTP requests processed | `method`, `endpoint`, `status` |
| **`mship_sink_retry_total`** | **Total retry attempts per sink** | **`sink`** |
| **`mship_sink_error_total`** | **Total errors per sink** | **`sink`** |
| **`mship_sink_timeout_total`** | **Total timeouts per sink** | **`sink`** |
| **`mship_sink_circuit_open_total`** | **Total circuit breaker opens per sink** | **`sink`** |
| **`mship_sink_dlq_total`** | **Total events sent to dead letter queue per sink** | **`sink`** |

### Histograms

| Metric | Description | Labels |
|--------|-------------|---------|
| `mship_ingest_seconds` | Time spent processing ingest requests | None |
| `mship_pipeline_seconds` | Time spent in processing pipeline | None |
| `mship_sink_write_seconds` | Time spent writing to each sink | `sink` |

### Gauges

| Metric | Description | Labels |
|--------|-------------|---------|
| `mship_active_connections` | Active database connections | None |
| `mship_loki_queue_size` | Current Loki batching queue size | None |
| **`mship_sink_circuit_state`** | **Circuit breaker state per sink (0=closed, 1=open, 2=half-open)** | **`sink`** |
| **`mship_sink_queue_size`** | **Current number of events in persistent queue per sink** | **`sink`** |
| **`mship_sink_queue_bytes`** | **Current size of persistent queue in bytes per sink** | **`sink`** |

## Useful PromQL Queries

### Event Rates
```promql
# Events per second ingested
rate(mship_ingest_events_total[1m])

# Events per second written (all sinks)
rate(mship_written_events_total[1m])

# Events per second per sink
rate(mship_sink_written_total[1m])
```

### Latency Percentiles
```promql
# 95th percentile ingest latency
histogram_quantile(0.95, rate(mship_ingest_seconds_bucket[5m]))

# 99th percentile pipeline latency
histogram_quantile(0.99, rate(mship_pipeline_seconds_bucket[5m]))

# 95th percentile sink write latency by sink
histogram_quantile(0.95, rate(mship_sink_write_seconds_bucket[5m]))
```

### Error Rates
```promql
# HTTP 5xx error rate
rate(mship_requests_total{status=~"5.."}[5m]) / rate(mship_requests_total[5m])

# Per-endpoint error rate
rate(mship_requests_total{status=~"5..",endpoint="/ingest"}[5m])
```

### Resource Usage
```promql
# Active database connections
mship_active_connections

# Loki queue depth
mship_loki_queue_size
```

### Reliability Monitoring

#### Retry and Error Rates
```promql
# Retry rate per sink (retries/second)  
rate(mship_sink_retry_total[1m])

# Error rate per sink (errors/second)
rate(mship_sink_error_total[1m])

# Timeout rate per sink (timeouts/second)
rate(mship_sink_timeout_total[1m])

# Success rate per sink (successful writes / total attempts)
rate(mship_sink_written_total[1m]) / (rate(mship_sink_written_total[1m]) + rate(mship_sink_error_total[1m]))
```

#### Circuit Breaker Monitoring
```promql
# Circuit breaker state by sink (0=closed, 1=open, 2=half-open)
mship_sink_circuit_state

# Circuit breaker opens per minute
rate(mship_sink_circuit_open_total[1m])

# Time since last circuit breaker open
time() - (mship_sink_circuit_open_total unless mship_sink_circuit_open_total offset 1m)
```

#### Queue and Backpressure Monitoring
```promql
# Persistent queue depth by sink
mship_sink_queue_size

# Persistent queue utilization (bytes)  
mship_sink_queue_bytes

# Dead letter queue rate (poison messages/second)
rate(mship_sink_dlq_total[1m])

# Queue growth rate (events/second added to queue)
rate(mship_sink_queue_size[1m])
```

## Alerts

The following alerts are configured in `prometheus/alerts.yml`:

### Latency Alerts
- **HighIngestLatency95th**: p95 ingest latency > 1s for 5min
- **HighPipelineLatency95th**: p95 pipeline latency > 1s for 5min  
- **HighSinkWriteLatency95th**: p95 sink write latency > 1s for 5min

### Availability Alerts
- **NoIngestEvents**: No events ingested for 10min
- **MothershipDown**: Service unreachable for 1min

### Sink Alerts
- **LokiWritesZero**: No Loki writes for 10min despite queued events
- **TSDBWritesZero**: No TimescaleDB writes for 10min despite ingested events

### Error Rate Alerts  
- **HighHTTPErrorRate**: HTTP 5xx error rate > 10% for 5min

### Reliability Alerts
- **HighSinkRetryRate**: Sink retry rate > 5 retries/min for 10min
- **SinkCircuitBreakerOpen**: Circuit breaker open for > 5min
- **HighSinkErrorRate**: Sink error rate > 1 error/min for 5min  
- **SinkQueueBackpressure**: Persistent queue > 80% capacity for 10min
- **HighDLQRate**: Dead letter queue rate > 0.1 events/min for 5min
- **SinkTimeoutSpike**: Sink timeout rate > 0.5 timeouts/min for 5min

## Alerting Setup

### Default Configuration
By default, all alerts are sent to a "null" receiver that discards them. This is safe for development and testing.

### Enable Slack Notifications
1. Create a Slack webhook: https://api.slack.com/messaging/webhooks
2. Edit `alertmanager/config.yml`:
   ```yaml
   receivers:
   - name: 'critical-alerts'
     slack_configs:
       - api_url: 'YOUR_WEBHOOK_URL_HERE'
         channel: '#alerts-critical'
         title: 'Critical Alert: {{ .GroupLabels.alertname }}'
         text: '{{ range .Alerts }}{{ .Annotations.description }}{{ end }}'
   ```
3. Restart Alertmanager: `docker-compose restart alertmanager`

### Enable Email Notifications
1. Configure SMTP settings in `alertmanager/config.yml`
2. Add email configurations to receivers
3. Restart Alertmanager

## Dashboards

### EdgeBot Observability Dashboard
The main dashboard (`edgebot-observability.json`) includes:

- **Event Processing**: Ingestion rates, batch rates, per-sink rates
- **Latency**: p95 latencies for ingest, pipeline, and sink operations
- **Logs**: Application logs with service/environment filtering

### Variables
- `$service`: Filter logs by service name
- `$env`: Filter logs by environment

## Troubleshooting

### Prometheus Not Scraping Mothership
**Symptoms**: No `mship_*` metrics in Prometheus

**Solutions**:
1. Check mothership is running on port 8080: `curl http://localhost:8080/metrics`
2. Verify `host.docker.internal` resolves inside Prometheus container
3. Check Prometheus targets: http://localhost:9090/targets
4. Review Prometheus logs: `docker-compose logs prometheus`

### No Data in Grafana
**Symptoms**: Dashboard shows "No data" 

**Solutions**:
1. Verify datasources are configured: Grafana → Configuration → Data Sources
2. Check Prometheus URL in Grafana: `http://prometheus:9090`
3. Test queries directly in Prometheus: http://localhost:9090/graph
4. Ensure time range covers when mothership was running with traffic

### Alerts Not Firing
**Symptoms**: Expected alerts don't show in Alertmanager

**Solutions**:
1. Check alert rules syntax: http://localhost:9090/rules
2. Verify alert evaluation: http://localhost:9090/alerts  
3. Check Alertmanager configuration: http://localhost:9093/#/status
4. Review Prometheus logs for rule evaluation errors

### High Latency Alerts
**Symptoms**: HighIngestLatency95th firing

**Investigation**:
1. Check system resources (CPU, memory, disk I/O)
2. Examine database connection pool usage
3. Review sink-specific latency: `histogram_quantile(0.95, rate(mship_sink_write_seconds_bucket[5m]))`
4. Check for database or Loki connectivity issues

### No Sink Writes  
**Symptoms**: LokiWritesZero or TSDBWritesZero alerts

**Investigation**:
1. Check sink configuration: `LOKI_ENABLED`, `TSDB_ENABLED` 
2. Verify sink connectivity (database, Loki URL)
3. Review mothership logs for sink errors
4. Check queue sizes: `mship_loki_queue_size`

### Circuit Breaker Issues
**Symptoms**: SinkCircuitBreakerOpen alerts

**Investigation**:
1. Check circuit breaker state: `mship_sink_circuit_state{sink="tsdb"}` or `{sink="loki"}`
2. Review error rates: `rate(mship_sink_error_total[5m])`
3. Check recent failures in mothership logs
4. Verify downstream service health (database, Loki)
5. Consider tuning failure thresholds if too sensitive

### High Retry Rates
**Symptoms**: HighSinkRetryRate alerts

**Investigation**:
1. Check retry rates: `rate(mship_sink_retry_total[5m])`
2. Identify retry causes: review error types in logs
3. Check network connectivity to downstream services
4. Monitor timeout rates: `rate(mship_sink_timeout_total[5m])`
5. Consider increasing initial backoff if retry storms occur

### Queue Backpressure  
**Symptoms**: SinkQueueBackpressure alerts

**Investigation**:
1. Check queue utilization: `mship_sink_queue_bytes / queue_max_bytes * 100`
2. Monitor queue growth: `rate(mship_sink_queue_size[1m])`  
3. Verify queue processing is working (no stuck circuit breakers)
4. Check disk space in queue directories
5. Consider increasing `QUEUE_MAX_BYTES` or improving downstream performance

### High Dead Letter Queue Rate
**Symptoms**: HighDLQRate alerts  

**Investigation**:
1. Check DLQ rate: `rate(mship_sink_dlq_total[5m])`
2. Examine DLQ database contents for poison message patterns
3. Review event validation logic
4. Check for data format changes causing consistent failures
5. Consider event schema evolution

## Configuration Reference

### Environment Variables
| Variable | Default | Description |
|----------|---------|-------------|
| `LOKI_ENABLED` | `false` | Enable Loki log sink |
| `LOKI_URL` | `http://localhost:3100` | Loki push URL |
| `TSDB_ENABLED` | `true` | Enable TimescaleDB sink |
| **`LOKI_MAX_RETRIES`** | **`3`** | **Maximum retry attempts for Loki** |
| **`LOKI_INITIAL_BACKOFF_MS`** | **`1000`** | **Initial backoff in milliseconds** |  
| **`LOKI_MAX_BACKOFF_MS`** | **`60000`** | **Maximum backoff in milliseconds** |
| **`LOKI_JITTER_FACTOR`** | **`0.1`** | **Jitter factor (0.0-1.0)** |
| **`LOKI_TIMEOUT_MS`** | **`30000`** | **Request timeout in milliseconds** |
| **`LOKI_FAILURE_THRESHOLD`** | **`5`** | **Circuit breaker failure threshold** |
| **`LOKI_OPEN_DURATION_SEC`** | **`60`** | **Circuit breaker open duration** |
| **`LOKI_HALF_OPEN_MAX_INFLIGHT`** | **`2`** | **Max concurrent requests in half-open** |
| **`LOKI_QUEUE_ENABLED`** | **`false`** | **Enable persistent queue for Loki** |
| **`LOKI_QUEUE_DIR`** | **`./queues`** | **Queue storage directory** |
| **`LOKI_QUEUE_MAX_BYTES`** | **`104857600`** | **Max queue size (100MB)** |
| **`LOKI_QUEUE_FLUSH_INTERVAL_MS`** | **`5000`** | **Queue processing interval** |
| **`LOKI_DLQ_DIR`** | **`./dlq`** | **Dead letter queue directory** |
| **`TSDB_MAX_RETRIES`** | **`3`** | **Maximum retry attempts for TSDB** |
| **`TSDB_INITIAL_BACKOFF_MS`** | **`1000`** | **Initial backoff in milliseconds** |
| **`TSDB_MAX_BACKOFF_MS`** | **`60000`** | **Maximum backoff in milliseconds** |
| **`TSDB_JITTER_FACTOR`** | **`0.1`** | **Jitter factor (0.0-1.0)** |
| **`TSDB_TIMEOUT_MS`** | **`30000`** | **Request timeout in milliseconds** |
| **`TSDB_FAILURE_THRESHOLD`** | **`5`** | **Circuit breaker failure threshold** |
| **`TSDB_OPEN_DURATION_SEC`** | **`60`** | **Circuit breaker open duration** |
| **`TSDB_HALF_OPEN_MAX_INFLIGHT`** | **`2`** | **Max concurrent requests in half-open** |
| **`TSDB_QUEUE_ENABLED`** | **`false`** | **Enable persistent queue for TSDB** |
| **`TSDB_QUEUE_DIR`** | **`./queues`** | **Queue storage directory** |
| **`TSDB_QUEUE_MAX_BYTES`** | **`104857600`** | **Max queue size (100MB)** |
| **`TSDB_QUEUE_FLUSH_INTERVAL_MS`** | **`5000`** | **Queue processing interval** |
| **`TSDB_DLQ_DIR`** | **`./dlq`** | **Dead letter queue directory** |

### Ports
| Service | Port | Description |
|---------|------|-------------|
| Mothership | 8080 | Metrics endpoint `/metrics` |
| Grafana | 3000 | Web UI |
| Prometheus | 9090 | Web UI and API |
| Alertmanager | 9093 | Web UI and API |
| Loki | 3100 | Log ingestion and queries |

### File Locations  
| Component | Configuration File |
|-----------|-------------------|
| Prometheus | `prometheus/prometheus.yml` |
| Alert Rules | `prometheus/alerts.yml` |
| Alertmanager | `alertmanager/config.yml` |
| Grafana Datasources | `grafana/provisioning/datasources/` |
| Grafana Dashboards | `grafana/provisioning/dashboards/` |

## Best Practices

### 1. Label Cardinality
- Keep Loki labels low cardinality (service, env, severity)
- Avoid high-cardinality labels like IDs, timestamps, IPs
- Use safe labels defined in `loki.py`: type, service, host, site, env, severity

### 2. Alert Tuning
- Start with loose thresholds and tighten based on baseline performance
- Use appropriate `for` durations to avoid alert flapping
- Group related alerts to reduce noise

### 3. Dashboard Design
- Focus on key business metrics (event rates, latency, errors)
- Use appropriate time ranges (1h for operational, 24h for trends)
- Include both metrics and logs for correlation

### 4. Metric Collection
- Monitor sink performance separately 
- Track both throughput (events/s) and latency (p95, p99)
- Include error rates and queue depths

## Further Reading

- [Prometheus Documentation](https://prometheus.io/docs/)
- [Grafana Documentation](https://grafana.com/docs/)
- [Loki Documentation](https://grafana.com/docs/loki/)
- [Alertmanager Configuration](https://prometheus.io/docs/alerting/latest/configuration/)
- [PromQL Tutorial](https://prometheus.io/docs/prometheus/latest/querying/basics/)