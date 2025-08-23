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

To test email notifications work, you can temporarily trigger an alert:

1. **Lower the HighIngestLatency95th threshold** to trigger easily:
   ```bash
   # Edit prometheus/alerts.yml temporarily
   sed -i 's/> 1.0/> 0.001/' prometheus/alerts.yml
   ```

2. **Restart Prometheus to reload rules**:
   ```bash
   docker compose -f compose.observability.yml restart prometheus
   ```

3. **Start mothership to generate metrics**:
   ```bash
   cd mothership
   python -m app.server
   ```

4. **Send some test data** to trigger latency metrics:
   ```bash
   curl -X POST http://localhost:8080/ingest -H "Content-Type: application/json" -d '{"test": "data"}'
   ```

5. **Check for alerts** in Alertmanager: http://localhost:9093/#/alerts

6. **Wait for email** (should arrive within ~10 seconds if alert fires)

7. **Restore the original threshold**:
   ```bash
   git checkout prometheus/alerts.yml
   docker compose -f compose.observability.yml restart prometheus
   ```

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