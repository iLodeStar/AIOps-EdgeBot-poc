# Technical and Framework Decisions

Language and runtime
- Python 3.11 for improved async performance and typing

Async stack
- httpx for HTTP client with async support
- aiofiles for async file IO
- asyncio for concurrency

Data handling
- JSON as the interchange format
- Gzip compression for network efficiency
- Sanitization removes internal fields (e.g., __spool_id) prior to output

Reliability
- Batching and buffering to smooth bursts
- Exponential backoff retries for transient failures
- File output mode for simple deployments and air-gapped sites

Containerization
- Dockerfile runs as non-root (security best practice)
- Healthcheck and exposed ports are explicit
- Docker Compose simplifies single-host deployment

Observability
- Health and metrics endpoints for quick diagnostics
- Structured logs (JSON-capable via logger)

Security posture
- Optional HTTPS + token auth for mothership uploads
- Minimal network surface (only needed ports)
- No secrets in code; environment variables or config file usage