# AIOps EdgeBot - Operational Workflow

This document describes the operational workflows and data flow patterns in the AIOps EdgeBot system.

## Core Data Flow Workflow

```mermaid
graph TD
    subgraph "Data Sources"
        A1[Syslog UDP/TCP]
        A2[SNMP Devices]
        A3[Weather API]
        A4[Log Files]
        A5[NMEA GPS]
        A6[Network Flows]
    end

    subgraph "EdgeBot (Phase 1)"
        B1[Input Listeners]
        B2[Message Parser]
        B3[Data Normalizer]
        B4[Batch Buffer]
        B5[Output Shipper]
        B6[Health/Metrics]
        
        B1 --> B2
        B2 --> B3
        B3 --> B4
        B4 --> B5
    end

    subgraph "Transport Layer"
        C1[HTTP/HTTPS]
        C2[File Output]
        C3[Retry Queue]
        
        B5 --> C1
        B5 --> C2
        C1 --> C3
        C3 --> C1
    end

    subgraph "Mothership (Phase 1.5)"
        D1[Ingestion API]
        D2[Processing Pipeline]
        D3[Sink Dispatcher]
        D4[Health/Metrics]
        
        D1 --> D2
        D2 --> D3
    end

    subgraph "Processing Pipeline"
        E1[Redaction Phase]
        E2[Enrichment Phase]
        E3[LLM Enhancement]
        E4[Quality Validation]
        
        E1 --> E2
        E2 --> E3
        E3 --> E4
    end

    subgraph "Storage Sinks"
        F1[TimescaleDB]
        F2[Loki]
        F3[Future Sinks]
    end

    subgraph "Observability Stack"
        G1[Prometheus]
        G2[Grafana]
        G3[Alertmanager]
    end

    %% Data flow connections
    A1 --> B1
    A2 --> B1
    A3 --> B1
    A4 --> B1
    A5 --> B1
    A6 --> B1

    C1 --> D1
    D2 --> E1
    
    D3 --> F1
    D3 --> F2
    D3 --> F3

    B6 --> G1
    D4 --> G1
    G1 --> G2
    G1 --> G3

    %% Styling
    classDef input fill:#e1f5fe
    classDef process fill:#f3e5f5
    classDef storage fill:#e8f5e8
    classDef observability fill:#fff3e0

    class A1,A2,A3,A4,A5,A6 input
    class B1,B2,B3,B4,B5,D1,D2,D3,E1,E2,E3,E4 process
    class F1,F2,F3 storage
    class G1,G2,G3 observability
```

## Deployment Workflow

```mermaid
graph TD
    subgraph "Development"
        A1[Code Changes]
        A2[Unit Tests]
        A3[E2E Tests]
        A4[Linting/Format]
    end

    subgraph "CI/CD Pipeline"
        B1[GitHub Actions]
        B2[Build Images]
        B3[Security Scan]
        B4[Integration Tests]
    end

    subgraph "Deployment Options"
        C1[Docker Compose<br/>Single Host]
        C2[Kubernetes<br/>Helm Charts]
        C3[Edge Deployment<br/>Standalone]
    end

    subgraph "Monitoring Setup"
        D1[Configure Prometheus]
        D2[Setup Grafana Dashboards]
        D3[Configure Alerts]
        D4[Log Aggregation]
    end

    A1 --> A2
    A2 --> A3
    A3 --> A4
    A4 --> B1

    B1 --> B2
    B2 --> B3
    B3 --> B4

    B4 --> C1
    B4 --> C2
    B4 --> C3

    C1 --> D1
    C2 --> D1
    C3 --> D1

    D1 --> D2
    D2 --> D3
    D2 --> D4

    classDef dev fill:#e3f2fd
    classDef ci fill:#f1f8e9
    classDef deploy fill:#fff8e1
    classDef monitor fill:#fce4ec

    class A1,A2,A3,A4 dev
    class B1,B2,B3,B4 ci
    class C1,C2,C3 deploy
    class D1,D2,D3,D4 monitor
```

## Message Processing Workflow

```mermaid
sequenceDiagram
    participant SL as Syslog Source
    participant EB as EdgeBot
    participant MS as Mothership
    participant LO as Loki
    participant TS as TimescaleDB
    participant PR as Prometheus

    Note over SL,TS: Normal Message Flow

    SL->>EB: Raw syslog message
    EB->>EB: Parse & normalize
    EB->>EB: Buffer & batch
    EB->>MS: HTTP POST /ingest
    
    MS->>MS: Redaction processing
    MS->>MS: Enrichment processing
    MS->>MS: Optional LLM processing
    
    par Dual-Sink Storage
        MS->>LO: Send to Loki
        and
        MS->>TS: Send to TimescaleDB
    end

    MS-->>EB: 200 OK response
    
    Note over EB,PR: Metrics Collection
    EB->>PR: Export metrics
    MS->>PR: Export metrics

    Note over SL,TS: Error Recovery Flow

    SL->>EB: Raw message
    EB->>EB: Process message
    EB->>MS: HTTP POST /ingest (fails)
    EB->>EB: Queue for retry
    
    loop Retry Logic
        EB->>MS: Retry POST /ingest
        alt Success
            MS-->>EB: 200 OK
        else Failure
            EB->>EB: Exponential backoff
        end
    end
```

## Operational Scenarios

### 1. Normal Operations

**Daily Data Flow**:
1. EdgeBot collects ~1000-10000 messages/hour from various sources
2. Messages batched and shipped to Mothership every 30 seconds
3. Mothership processes with <100ms latency per batch
4. Data stored in both Loki (searchable) and TimescaleDB (analytics)
5. Grafana dashboards updated in real-time
6. Prometheus alerting monitors for anomalies

**Key Metrics to Monitor**:
- `edgebot_messages_received_total` - Input rate
- `mothership_pipeline_duration_seconds` - Processing latency  
- `mothership_ingestion_events_total` - Throughput
- `loki_ingester_chunks_stored_total` - Storage rate

### 2. Failure Recovery

**Mothership Downtime**:
1. EdgeBot detects failed HTTP requests
2. Messages queued in persistent SQLite queue
3. Exponential backoff retry (500ms → 5s → 30s)
4. Circuit breaker prevents overwhelming failed service
5. Once Mothership recovers, queue drains automatically
6. No data loss during outages

**Storage Sink Failure**:
1. Mothership detects Loki/TimescaleDB unavailability
2. Failed messages queued in persistent storage
3. Continues processing to available sinks
4. Automatic retry when sink recovers
5. Health endpoint reflects individual sink status

### 3. Scaling Scenarios

**High Volume Events**:
1. EdgeBot increases batch sizes dynamically
2. Mothership processes larger batches in parallel
3. Storage sinks scale based on ingestion rate
4. Monitoring alerts on latency/queue depth increases

**Multi-EdgeBot Deployment**:
1. Multiple EdgeBot instances → Single Mothership
2. Load balanced via HTTP client-side balancing
3. Mothership horizontally scalable with shared storage
4. Prometheus aggregates metrics across all instances

## Configuration Workflows

### EdgeBot Configuration
```yaml
# Typical production EdgeBot config
inputs:
  syslog:
    enabled: true
    udp_port: 5514
  snmp:
    enabled: true
    community: "public"
    
output:
  mothership:
    url: "https://mothership.company.com/ingest"
    batch_size: 100
    flush_interval_sec: 30
```

### Mothership Configuration  
```yaml
# Typical production Mothership config
sinks:
  loki:
    enabled: true
    url: "http://loki:3100"
  tsdb:
    enabled: true
    connection: "postgresql://user:pass@tsdb:5432/logs"

pipeline:
  processors:
    - type: "drop_fields"
    - type: "add_tags"
    - type: "geo_enrich"
```

## Monitoring Workflows

### Health Checking
1. **EdgeBot**: `GET /healthz` - Service health + input status
2. **Mothership**: `GET /healthz` - Service health + sink status  
3. **External**: Prometheus `up` metric for service availability

### Alert Workflows
1. **High Error Rate**: >5% failed messages in 5 minutes
2. **Queue Depth**: >1000 pending messages for >10 minutes
3. **Sink Unavailable**: Any storage sink down >2 minutes
4. **Resource Usage**: CPU/Memory >80% for >5 minutes

### Troubleshooting Workflow
1. Check service health endpoints
2. Review Grafana dashboards for anomalies  
3. Query Loki for error patterns
4. Examine Prometheus metrics for bottlenecks
5. Review application logs for detailed errors

## Testing Workflows

See the comprehensive E2E testing framework:
- `make test-unit` - Run all unit tests
- `make test-e2e` - Run end-to-end integration tests
- `make e2e-up` - Start test infrastructure
- `./scripts/run_tests.sh` - Generate full test reports