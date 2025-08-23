# EdgeBot Observability Guide

This guide covers the complete observability stack for EdgeBot, including Prometheus metrics, Loki logs, Grafana dashboards, and alerting through Alertmanager.

## Quick Start

### 1. Start the Observability Stack

```bash
# Start all services (Prometheus, Alertmanager, Grafana, Loki)
docker compose -f compose.observability.yml up -d

# Check that all services are healthy
docker compose -f compose.observability.yml ps
```

### 2. Access the Services

| Service | URL | Credentials |
|---------|-----|-------------|
| **Grafana** | http://localhost:3000 | admin/admin |
| **Prometheus** | http://localhost:9090 | None |
| **Alertmanager** | http://localhost:9093 | None |
| **Loki** | http://localhost:3100 | None |

### 3. Configure Email Alerts (Optional)

To enable email notifications:

```bash
# Copy environment template
cp .env.example .env

# Edit .env with your SMTP settings
# Then restart Alertmanager
docker compose -f compose.observability.yml restart alertmanager

# Test email notifications
./scripts/test_email_alerts.sh
```

### 4. Start the Mothership

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

Email notifications allow you to receive alerts via email when critical or warning events occur in your EdgeBot deployment.

#### Step 1: Configure SMTP Settings

Create a `.env` file in the root directory (or copy from `.env.example`):

```bash
cp .env.example .env
```

Edit `.env` and configure your SMTP settings:

```bash
# SMTP server settings
ALERT_SMTP_HOST=smtp.gmail.com
ALERT_SMTP_PORT=587
ALERT_SMTP_USER=your-email@gmail.com
ALERT_SMTP_PASS=your-app-password
ALERT_SMTP_STARTTLS=true

# Email sender and recipients
ALERT_EMAIL_FROM=alertmanager@yourcompany.com
ALERT_EMAIL_TO=ops-team@yourcompany.com

# For multiple recipients, separate with commas:
# ALERT_EMAIL_TO=admin1@yourcompany.com,admin2@yourcompany.com
```

**SMTP Configuration Examples:**

- **Gmail**: Use `smtp.gmail.com:587` with an [App Password](https://support.google.com/accounts/answer/185833)
- **Outlook/Hotmail**: Use `smtp-mail.outlook.com:587`
- **Yahoo**: Use `smtp.mail.yahoo.com:587`
- **Corporate SMTP**: Check with your IT department for server details

#### Step 2: Start/Restart the Observability Stack

```bash
# Start the stack (will automatically load .env file)
docker compose -f compose.observability.yml up -d

# Or restart if already running
docker compose -f compose.observability.yml restart alertmanager
```

#### Step 3: Verify Configuration

1. Check Alertmanager status: http://localhost:9093/#/status
2. Look for email receiver configuration in the "Config" section
3. Verify no configuration errors are shown

#### Step 4: Test Email Delivery (Synthetic Test)

**Quick Test (Recommended)**

Use the provided test script to verify email notifications:

```bash
# Run the automated test script
./scripts/test_email_alerts.sh
```

This script will:
- Check if the observability stack is running
- Verify your email configuration
- Create a temporary test alert that fires immediately
- Wait for email delivery
- Clean up automatically

**Manual Test Methods**

If you prefer manual testing, you can use one of these approaches:

**Method 1: Trigger a High Latency Alert**

1. **Start the observability stack**:
   ```bash
   docker compose -f compose.observability.yml up -d
   ```

2. **Create a test script** to generate synthetic latency metrics:
   ```bash
   # Create test script
   cat > test_alert.sh << 'EOF'
   #!/bin/bash
   
   echo "Starting synthetic alert test..."
   
   # Temporarily lower the HighIngestLatency95th threshold to 0.001s (1ms)
   cp prometheus/alerts.yml prometheus/alerts.yml.backup
   sed -i 's/> 1\.0/> 0.001/' prometheus/alerts.yml
   
   # Restart Prometheus to reload rules
   docker compose -f compose.observability.yml restart prometheus
   
   echo "Waiting 30s for Prometheus to reload rules..."
   sleep 30
   
   # Start mothership (which will have some initial latency)
   cd mothership
   python -m app.server &
   MOTHERSHIP_PID=$!
   
   echo "Waiting 60s for alert to potentially fire..."
   sleep 60
   
   # Check if alert is firing
   echo "Checking alerts in Alertmanager:"
   curl -s http://localhost:9093/api/v1/alerts | jq '.data[].labels.alertname' 2>/dev/null || echo "jq not available, check http://localhost:9093/#/alerts manually"
   
   # Cleanup
   kill $MOTHERSHIP_PID 2>/dev/null
   cd ..
   mv prometheus/alerts.yml.backup prometheus/alerts.yml
   docker compose -f compose.observability.yml restart prometheus
   
   echo "Test complete. Check your email and http://localhost:9093/#/alerts"
   EOF
   
   chmod +x test_alert.sh
   ./test_alert.sh
   ```

**Method 2: Create a Manual Test Alert**

1. **Add a test alert rule**:
   ```bash
   # Add to prometheus/alerts.yml temporarily
   cat >> prometheus/alerts.yml << 'EOF'
   
     # Test alert for email verification
     - alert: EmailTestAlert
       expr: vector(1)  # Always fires
       for: 0m
       labels:
         severity: warning
         component: test
       annotations:
         summary: "Test alert for email verification"
         description: "This is a test alert to verify email notifications are working"
   EOF
   ```

2. **Restart Prometheus**:
   ```bash
   docker compose -f compose.observability.yml restart prometheus
   ```

3. **Wait for alert to fire** (should appear within 1 minute):
   ```bash
   # Check alerts
   curl -s http://localhost:9093/api/v1/alerts | jq '.data[]'
   ```

4. **Clean up the test alert**:
   ```bash
   # Remove the test alert from prometheus/alerts.yml
   git checkout prometheus/alerts.yml
   docker compose -f compose.observability.yml restart prometheus
   ```

**Verification Steps:**
1. Check email inbox for alert notifications
2. Visit http://localhost:9093/#/alerts to see active alerts
3. Check Alertmanager logs: `docker compose -f compose.observability.yml logs alertmanager`

#### Troubleshooting Email Notifications

**No emails received:**
1. Check Alertmanager logs: `docker compose -f compose.observability.yml logs alertmanager`
2. Verify SMTP credentials are correct
3. Check spam folder
4. For Gmail, ensure "Less secure app access" is enabled or use App Password

**Authentication errors:**
1. For Gmail: Use an [App Password](https://support.google.com/accounts/answer/185833) instead of your regular password
2. Enable 2-factor authentication first, then generate an App Password

**Connection errors:**
1. Verify SMTP host and port are correct
2. Check if your network/firewall blocks SMTP ports
3. Try different STARTTLS settings (true/false)

**Configuration errors:**
1. Check Alertmanager config at: http://localhost:9093/#/status
2. Verify `.env` file variables are loaded correctly
3. Restart the observability stack after configuration changes

#### Security Considerations

- **Never commit** your `.env` file with real credentials to version control
- Use strong, unique passwords for SMTP authentication
- Consider using App Passwords instead of your main email password
- For production deployments, use Docker Secrets or Kubernetes Secrets:

```yaml
# Docker Swarm example
secrets:
  smtp_password:
    external: true

services:
  alertmanager:
    secrets:
      - smtp_password
    environment:
      - ALERT_SMTP_PASS_FILE=/run/secrets/smtp_password
```

#### Kubernetes Deployment

For Kubernetes deployments, store SMTP credentials in a Secret:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: alertmanager-smtp
type: Opaque
stringData:
  smtp-user: your-email@gmail.com
  smtp-pass: your-app-password
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: alertmanager
spec:
  template:
    spec:
      containers:
      - name: alertmanager
        env:
        - name: ALERT_SMTP_USER
          valueFrom:
            secretKeyRef:
              name: alertmanager-smtp
              key: smtp-user
        - name: ALERT_SMTP_PASS
          valueFrom:
            secretKeyRef:
              name: alertmanager-smtp
              key: smtp-pass
```

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
| `ALERT_SMTP_HOST` | - | SMTP server hostname for email alerts |
| `ALERT_SMTP_PORT` | `587` | SMTP server port |
| `ALERT_SMTP_USER` | - | SMTP username for authentication |
| `ALERT_SMTP_PASS` | - | SMTP password for authentication |
| `ALERT_SMTP_STARTTLS` | `true` | Enable STARTTLS for SMTP |
| `ALERT_EMAIL_FROM` | `alertmanager@edgebot.local` | Sender email address |
| `ALERT_EMAIL_TO` | - | Recipient email address(es), comma-separated |
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