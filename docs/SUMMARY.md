# AIOps EdgeBot - System Summary

## Overview

AIOps EdgeBot is a distributed observability data collection and processing system designed for edge computing environments. The system consists of two main phases:

### Phase 1: EdgeBot (Data Collector)
**Location**: `edge_node/`

EdgeBot is a lightweight, resilient data collector that runs at the edge to gather observability data from multiple sources:

- **Input Sources**:
  - Syslog (UDP/TCP) - System and application logs
  - SNMP - Network device monitoring
  - Weather API - Environmental data
  - File Tailing - Log file monitoring
  - NMEA - GPS/maritime data
  - Network Flows - Traffic analysis

- **Output Capabilities**:
  - File output (JSON) - Local storage
  - HTTP shipping to Mothership - Centralized processing
  - Configurable batching and retry logic
  - Gzip compression for efficient transport

- **Key Features**:
  - Health and metrics endpoints (`/healthz`, `/metrics`)
  - Configuration-driven architecture
  - Docker containerization
  - Reliable message buffering and retry mechanisms

### Phase 1.5: Mothership (Data Processor)
**Location**: `mothership/`

Mothership is the centralized data processing service that enriches and routes data to multiple storage backends:

- **Processing Pipeline**:
  1. **Redaction Phase** - PII removal and data sanitization
  2. **Enrichment Phase** - Tag addition, geo-location, severity mapping
  3. **LLM Enhancement** - Optional AI-powered analysis (feature-flagged OFF by default)
  4. **Dual-Sink Storage** - Fanout to multiple storage systems

- **Storage Backends**:
  - **TimescaleDB** - Time-series analytics and queries
  - **Loki** - Log aggregation and search
  - Configurable sink routing and failover

- **API Endpoints**:
  - `POST /ingest` - Event ingestion from EdgeBot
  - `GET /healthz` - Service health with sink status
  - `GET /metrics` - Prometheus metrics
  - `GET /stats` - Detailed processing statistics

## Architecture Flow

```
┌─────────────┐    HTTP/HTTPS     ┌──────────────────┐    
│   EdgeBot   │─────────────────▶│    Mothership    │    
│  (Phase 1)  │   JSON Batches    │   (Phase 1.5)    │    
└─────────────┘                  └──────────────────┘    
       │                                    │              
   Syslog/SNMP                    ┌─────────▼──────────┐   
   Weather/Files                  │   Processing       │   
   NMEA/Flows                     │   Pipeline         │   
                                  │                    │   
                                  │ 1. Redaction       │   
                                  │ 2. Enrichment      │   
                                  │ 3. LLM (Optional)  │   
                                  └─────────┬──────────┘   
                                            │              
                                  ┌─────────▼──────────┐   
                                  │   Dual-Sink        │   
                                  │   Storage          │   
                                  └─────────┬──────────┘   
                                            │              
                          ┌─────────────────┼─────────────────┐
                          │                 │                 │
                    ┌─────▼─────┐    ┌──────▼──────┐    ┌─────▼─────┐
                    │TimescaleDB│    │    Loki     │    │  Grafana  │
                    │(Analytics)│    │(Log Search) │    │(Dashboard)│
                    └───────────┘    └─────────────┘    └───────────┘
```

## Key Technologies

- **Language**: Python 3.11+ (async/await throughout)
- **Web Framework**: FastAPI (Mothership), aiohttp (EdgeBot)
- **Data Format**: JSON with gzip compression
- **Containerization**: Docker with multi-stage builds
- **Observability**: Prometheus metrics, structured logging
- **Database**: TimescaleDB (PostgreSQL), Loki
- **Message Queue**: Built-in persistent queues with SQLite

## Deployment Options

1. **Single Host**: Docker Compose with observability stack
2. **Kubernetes**: Helm charts for scalable deployment
3. **Edge Deployment**: Lightweight EdgeBot with file output
4. **Hybrid Cloud**: EdgeBot → Cloud Mothership → Managed services

## Safety and Reliability

- **PII Protection**: Deterministic redaction before any LLM processing
- **Circuit Breakers**: Automatic failover on service degradation
- **Persistent Queues**: Message durability across restarts
- **Retry Logic**: Exponential backoff with jitter
- **Health Monitoring**: Multi-level health checks with dependency status

## Current Status

### ✅ Implemented
- Complete EdgeBot data collection (syslog, SNMP, weather, file tailing)
- Full Mothership processing pipeline with dual-sink support
- Comprehensive test suite (unit + end-to-end)
- Docker containerization and Kubernetes deployment
- Observability stack integration (Loki, Prometheus, Grafana)

### 🚧 In Development  
- Advanced LLM integrations (currently feature-flagged)
- Additional input sources (network flows, NMEA)
- Enhanced geo-location and enrichment features

### 📋 Planned
- Multi-tenant support
- Advanced alerting and anomaly detection
- Cloud-native scaling features
- Enhanced security and compliance features

## Getting Started

See `docs/LOCAL_SETUP.md` for step-by-step installation and configuration instructions.

For technical architecture details, see `docs/ARCHITECTURE.md`.

For operational workflows, see `docs/WORKFLOW.md`.