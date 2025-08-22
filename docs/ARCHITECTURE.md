# Architecture Overview

Purpose
- Collect, normalize, and ship edge telemetry (logs/metrics)
- Be reliable (buffering, retries), observable (health/metrics), and secure (non-root, TLS)

High-level diagram

[Inputs] --> [Buffer] --> [Batch + Sanitize] --> [Output Shipper] --> [File or HTTPS]
                 |                                   |
                 +--------- Retry Manager -----------+

Key components
- Inputs (edge_node/app/inputs)
  - Syslog server: listens on UDP 5514 and TCP 5515
  - SNMP poller and Weather collector (optional, disabled by default)
- Message Buffer
  - Stores messages in memory/disk (SQLite-backed when configured)
  - Supports batching and at-least-once delivery semantics
- Output Shipper (edge_node/app/output/shipper.py)
  - Builds a sanitized JSON envelope
  - Sends via:
    - File sink (writes .json and .json.gz)
    - HTTPS with gzip compression, auth token, TLS
  - Retry Manager with exponential backoff
- Observability
  - /healthz and /metrics endpoints
  - Structured logs
- Containerization
  - Dockerfile runs as non-root user
  - Docker Compose maps data and log volumes

Data format (envelope)
- messages: array of sanitized events
- batch_size, timestamp, source, is_retry
- No internal fields (e.g., __spool_id) are included

Reliability
- Buffer decouples inputs from output
- Batching reduces overhead and provides back-pressure
- Retries prevent data loss during transient failures

Security
- Non-root user inside container
- TLS and bearer token for HTTPS
- Configurable ports and minimal exposure

Performance
- Async IO (Python 3.11) with httpx and aiofiles
- Gzip compression for wire efficiency