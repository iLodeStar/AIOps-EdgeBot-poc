# EdgeBot Reliability Guide

This guide covers the reliability features in EdgeBot Mothership designed for challenging network environments including satellite links, at-sea deployments, and remote edge locations.

## Overview

EdgeBot includes comprehensive reliability features to handle network connectivity issues:

- **Per-sink retry policies** with exponential backoff and jitter
- **Circuit breakers** to prevent cascading failures  
- **Store-and-forward queuing** for temporary outages
- **Dead letter queues** for poison message handling
- **Comprehensive metrics** for monitoring and alerting

## Quick Start

### Basic Reliability (Default)

Every sink automatically includes retry and circuit breaker protection:

```bash
# TimescaleDB with basic reliability
python -m app.server

# Loki with basic reliability  
export LOKI_ENABLED=true
python -m app.server
```

### Store-and-Forward Mode

For unreliable networks, enable persistent queuing:

```bash
# Enable queuing for both sinks
export TSDB_QUEUE_ENABLED=true
export LOKI_QUEUE_ENABLED=true
export TSDB_QUEUE_DIR="/data/queues"
export LOKI_QUEUE_DIR="/data/queues"
python -m app.server
```

### Satellite/At-Sea Configuration  

Recommended settings for high-latency, lossy networks:

```bash
# Aggressive retry settings
export TSDB_MAX_RETRIES=5
export TSDB_INITIAL_BACKOFF_MS=2000
export TSDB_MAX_BACKOFF_MS=300000  # 5 minutes max
export TSDB_TIMEOUT_MS=120000      # 2 minute timeout

# Sensitive circuit breaker
export TSDB_FAILURE_THRESHOLD=3
export TSDB_OPEN_DURATION_SEC=300  # 5 minute recovery

# Large persistent queues
export TSDB_QUEUE_ENABLED=true
export TSDB_QUEUE_MAX_BYTES=1073741824  # 1GB queue
export TSDB_QUEUE_DIR="/data/queues"

python -m app.server
```

## Architecture

### Per-Sink Reliability Stack

```
┌─────────────────┐
│   Ingestion     │
│   Endpoint      │  
└─────────┬───────┘
          │
          ▼
┌─────────────────┐
│ Processing      │
│ Pipeline        │
└─────────┬───────┘
          │
          ▼
┌─────────────────┐    ┌─────────────────┐
│ Resilient Sink  │    │ Resilient Sink  │
│   (TSDB)        │    │   (Loki)        │
├─────────────────┤    ├─────────────────┤
│ Circuit Breaker │    │ Circuit Breaker │
│      ↓          │    │      ↓          │
│ Retry Manager   │    │ Retry Manager   │
│      ↓          │    │      ↓          │
│ Persistent      │    │ Persistent      │
│ Queue (opt)     │    │ Queue (opt)     │
│      ↓          │    │      ↓          │
│ Actual Sink     │    │ Actual Sink     │
└─────────────────┘    └─────────────────┘
```

### State Machine Flow

```
Normal Operation:
Events → Circuit Breaker (Closed) → Retry Manager → Sink

Network Issues:
Events → Circuit Breaker (Closed) → Retry Manager (fails) → Persistent Queue

Persistent Failures: 
Events → Circuit Breaker (Open) → Persistent Queue

Recovery:
Circuit Breaker (Half-Open) → Test Request → Success → Closed
Queue Processor → Retry Manager → Sink → Success → Drain Queue
```

## Configuration

### Retry Policy Configuration

```yaml
sinks:
  timescaledb:
    retry:
      enabled: true
      max_retries: 3              # Total retry attempts
      initial_backoff_ms: 1000    # Starting backoff  
      max_backoff_ms: 60000       # Backoff ceiling
      jitter_factor: 0.1          # Randomization (0.0-1.0)
      timeout_ms: 30000           # Per-request timeout
```

**Key Parameters:**

- `max_retries`: Total attempts before giving up (default: 3)
- `initial_backoff_ms`: Starting delay between retries (default: 1000ms)  
- `max_backoff_ms`: Maximum delay between retries (default: 60s)
- `jitter_factor`: Random variance to prevent thundering herd (default: 0.1)
- `timeout_ms`: Individual request timeout (default: 30s)

**Backoff Formula:**
```
delay = min(initial_backoff * (2 ^ attempt), max_backoff) + (jitter * random())
```

### Circuit Breaker Configuration

```yaml
sinks:
  timescaledb:
    circuit_breaker:
      enabled: true
      failure_threshold: 5        # Failures to trip breaker
      open_duration_sec: 60       # Time to stay open
      half_open_max_inflight: 2   # Test request limit
```

**State Transitions:**

1. **Closed** → **Open**: After `failure_threshold` consecutive failures
2. **Open** → **Half-Open**: After `open_duration_sec` timeout  
3. **Half-Open** → **Closed**: On successful request
4. **Half-Open** → **Open**: On failed request

### Store-and-Forward Configuration

```yaml
sinks:
  timescaledb:  
    queue:
      enabled: true
      queue_dir: "./queues"           # SQLite database location
      queue_max_bytes: 104857600      # 100MB queue limit
      queue_flush_interval_ms: 5000   # Processing frequency
      dlq_dir: "./dlq"                # Dead letter queue location
```

**Key Parameters:**

- `queue_max_bytes`: Total queue size limit (default: 100MB)
- `queue_flush_interval_ms`: How often to attempt queue processing (default: 5s)
- Queue automatically drains when connectivity is restored
- DLQ captures events that exceed retry limits

## Deployment Scenarios

### 1. Satellite Communication

**Challenges:** High latency (500-800ms), periodic dropouts, limited bandwidth

**Configuration:**
```bash
# Extended timeouts for high latency
export TSDB_TIMEOUT_MS=300000        # 5 minutes
export LOKI_TIMEOUT_MS=300000

# Conservative retry policy
export TSDB_MAX_RETRIES=5
export TSDB_INITIAL_BACKOFF_MS=5000  # 5 seconds
export TSDB_MAX_BACKOFF_MS=900000    # 15 minutes

# Circuit breaker tuned for periodic outages
export TSDB_FAILURE_THRESHOLD=3     
export TSDB_OPEN_DURATION_SEC=1800   # 30 minutes

# Essential: Enable queuing
export TSDB_QUEUE_ENABLED=true
export TSDB_QUEUE_MAX_BYTES=2147483648  # 2GB
```

### 2. At-Sea Operations

**Challenges:** Complete connectivity loss during storms, varying quality

**Configuration:**
```bash
# Aggressive queuing for extended outages
export TSDB_QUEUE_ENABLED=true
export LOKI_QUEUE_ENABLED=true
export TSDB_QUEUE_MAX_BYTES=5368709120  # 5GB
export LOKI_QUEUE_MAX_BYTES=1073741824  # 1GB

# Long circuit breaker recovery for storm outages  
export TSDB_OPEN_DURATION_SEC=3600   # 1 hour
export LOKI_OPEN_DURATION_SEC=3600

# Moderate retry policy
export TSDB_MAX_RETRIES=3
export TSDB_INITIAL_BACKOFF_MS=10000  # 10 seconds
export TSDB_MAX_BACKOFF_MS=600000     # 10 minutes
```

### 3. Remote Edge Sites

**Challenges:** Intermittent connectivity, power constraints, limited storage

**Configuration:**
```bash
# Balanced approach with storage constraints
export TSDB_QUEUE_ENABLED=true
export TSDB_QUEUE_MAX_BYTES=536870912   # 512MB
export LOKI_QUEUE_ENABLED=false         # Prioritize TSDB

# Fast recovery circuit breaker
export TSDB_FAILURE_THRESHOLD=5
export TSDB_OPEN_DURATION_SEC=120       # 2 minutes

# Standard retry policy  
export TSDB_MAX_RETRIES=3
export TSDB_INITIAL_BACKOFF_MS=2000     # 2 seconds
export TSDB_MAX_BACKOFF_MS=60000        # 1 minute
```

### 4. Multi-Cloud Deployments

**Challenges:** Cross-region latency, cloud provider outages

**Configuration:**
```bash
# Regional failover with queuing
export TSDB_QUEUE_ENABLED=true
export LOKI_QUEUE_ENABLED=true

# Quick circuit breaker for fast failover
export TSDB_FAILURE_THRESHOLD=3
export TSDB_OPEN_DURATION_SEC=60        # 1 minute
export LOKI_FAILURE_THRESHOLD=3  
export LOKI_OPEN_DURATION_SEC=60

# Moderate timeouts for cross-region calls
export TSDB_TIMEOUT_MS=60000            # 1 minute
export LOKI_TIMEOUT_MS=60000
```

## Monitoring and Alerting

### Key Metrics to Monitor

#### Reliability Health
```promql
# Circuit breaker open per sink
mship_sink_circuit_state == 1

# High retry rates (>1 retry/minute)  
rate(mship_sink_retry_total[5m]) > 0.017

# Queue utilization >80%
mship_sink_queue_bytes / 104857600 > 0.8
```

#### Performance Impact
```promql
# Increased latency due to retries
histogram_quantile(0.95, rate(mship_sink_write_seconds_bucket[5m])) > 2

# Events being queued instead of direct writes
rate(mship_sink_queue_size[5m]) > 0
```

#### Data Loss Risk
```promql  
# Dead letter queue growth (poison messages)
rate(mship_sink_dlq_total[5m]) > 0

# Queue approaching size limit
mship_sink_queue_bytes / 104857600 > 0.9
```

### Recommended Alerts

```yaml
# Critical Alerts
- name: sink-reliability
  rules:
  - alert: SinkCircuitBreakerOpen
    expr: mship_sink_circuit_state == 1
    for: 5m
    annotations:
      description: "{{ $labels.sink }} circuit breaker has been open for >5min"
      
  - alert: SinkQueueNearFull  
    expr: mship_sink_queue_bytes / 104857600 > 0.9
    for: 10m
    annotations:
      description: "{{ $labels.sink }} queue is >90% full"
      
  - alert: HighDeadLetterQueueRate
    expr: rate(mship_sink_dlq_total[5m]) > 0.01  # >0.6 events/min
    for: 5m
    annotations:
      description: "{{ $labels.sink }} has high DLQ rate: poison messages"

# Warning Alerts      
  - alert: HighSinkRetryRate
    expr: rate(mship_sink_retry_total[5m]) > 0.1  # >6 retries/min
    for: 10m
    annotations:
      description: "{{ $labels.sink }} retry rate is elevated"
      
  - alert: SinkQueueGrowth
    expr: rate(mship_sink_queue_size[5m]) > 1     # >60 events/min queued
    for: 15m  
    annotations:
      description: "{{ $labels.sink }} queue is growing consistently"
```

## Operations

### Queue Management

#### Queue Status
```bash
# Check queue databases
ls -la queues/
sqlite3 queues/tsdb.db "SELECT COUNT(*), SUM(LENGTH(event_data)) FROM queue"

# Check DLQ contents
sqlite3 dlq/tsdb_dlq.db "SELECT * FROM dlq ORDER BY created_at DESC LIMIT 10"
```

#### Queue Maintenance
```bash  
# Archive old DLQ entries (manually)
sqlite3 dlq/tsdb_dlq.db "DELETE FROM dlq WHERE created_at < date('now', '-30 days')"

# Emergency queue purge (data loss!)
rm queues/tsdb.db dlq/tsdb_dlq.db  # Will recreate automatically
```

#### Queue Recovery
```bash
# Force queue processing after outage
# Queues process automatically, but you can restart mothership to force immediate processing
systemctl restart mothership
```

### Troubleshooting

#### Retry Storm Detection
**Symptoms:** High CPU, elevated retry rates, slow response times

**Investigation:**
1. Check retry rates: `rate(mship_sink_retry_total[1m])`
2. Examine backoff settings: may be too aggressive
3. Review downstream service health
4. Consider increasing `initial_backoff_ms` or reducing `max_retries`

#### Circuit Breaker Stuck Open
**Symptoms:** All requests to sink failing, circuit_state = 1

**Investigation:**
1. Check downstream service availability  
2. Review failure patterns in logs
3. Verify `open_duration_sec` is not too long
4. Test manual connectivity to sink target
5. Consider reducing `failure_threshold` if too sensitive

#### Queue Overflow  
**Symptoms:** Queue bytes approaching limit, events being dropped

**Investigation:**
1. Check available disk space
2. Monitor queue growth rate vs processing rate
3. Verify circuit breakers are not preventing queue drainage
4. Consider increasing `queue_max_bytes` or improving sink performance
5. Check for stuck transactions preventing queue processing

#### Poison Messages in DLQ
**Symptoms:** Consistent DLQ growth, certain events always failing  

**Investigation:**
1. Examine DLQ contents for patterns
2. Check event schema validation  
3. Review recent application changes
4. Test problematic events manually
5. Consider event format migration strategy

### Best Practices

#### Disk Management
- Place queues on persistent storage (not `/tmp`)
- Monitor disk usage and set up rotation
- Consider using separate filesystem for queue data
- Ensure adequate I/O performance for SQLite operations

#### Configuration Tuning
- Start with conservative settings and tune based on baseline
- Test configuration changes in staging environment
- Use monitoring to guide parameter adjustment
- Document any deviations from defaults

#### Capacity Planning
- Queue size should accommodate expected outage duration
- Consider event size when setting `queue_max_bytes`
- Plan for 2-3x normal throughput during queue drainage
- Account for retry amplification in downstream capacity

#### Security
- Restrict access to queue directories (sensitive event data)
- Consider encrypting queue databases in hostile environments  
- Secure DLQ access (may contain sensitive failed events)
- Monitor queue directory permissions

#### Testing
- Regularly test outage scenarios in staging
- Verify queue processing after simulated network failures
- Test circuit breaker transitions under various failure modes  
- Validate retry behavior with downstream service simulators

## Performance Impact

### Resource Usage

#### Memory  
- Base: ~10MB per resilient sink for internal state
- Queue processing: Additional ~1MB per 1000 queued events in memory
- Circuit breaker state: Negligible (~1KB per sink)

#### Disk I/O
- Queue writes: 1 SQLite transaction per batch (typically <100 events)
- Queue reads: Batch reads during processing (configurable size)
- DLQ writes: Occasional, usually minimal unless systemic issues

#### Network
- Retries increase network usage proportionally to retry rate  
- Jitter reduces network synchronization effects
- Circuit breakers prevent unnecessary network load during outages

#### CPU
- Retry backoff calculations: Negligible
- Queue processing: ~0.1% CPU per 1000 events/minute
- Circuit breaker state management: Negligible

### Performance Tuning

#### Optimize for Throughput
```bash
# Larger batches, less frequent processing
export TSDB_QUEUE_FLUSH_INTERVAL_MS=10000  # 10 seconds
# Increase timeout for larger batches  
export TSDB_TIMEOUT_MS=60000               # 1 minute
```

#### Optimize for Latency
```bash
# Smaller batches, more frequent processing
export TSDB_QUEUE_FLUSH_INTERVAL_MS=1000   # 1 second
# Faster circuit breaker recovery
export TSDB_OPEN_DURATION_SEC=30           # 30 seconds  
```

#### Optimize for Resource Usage
```bash
# Smaller queues
export TSDB_QUEUE_MAX_BYTES=52428800       # 50MB
# Fewer retries
export TSDB_MAX_RETRIES=2
```

## Further Reading

- [Prometheus Monitoring Guide](OBSERVABILITY.md)
- [Circuit Breaker Pattern](https://martinfowler.com/bliki/CircuitBreaker.html)
- [Exponential Backoff Best Practices](https://cloud.google.com/storage/docs/retry-strategy)
- [SQLite Performance Tips](https://www.sqlite.org/performance.html)