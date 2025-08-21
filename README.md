# AIOps EdgeBot POC

A proof-of-concept implementation of an AIOps EdgeBot system featuring edge telemetry collection, centralized anomaly detection, and real-time monitoring capabilities.

## Architecture Overview

```
┌─────────────────┐    HTTP/JSON    ┌─────────────────────┐
│   Edge Node     │ ──────────────→ │  Central Platform   │
│   (Port 8001)   │    telemetry    │      (Port 8000)    │
│                 │                 │                     │
│ - Telemetry sim │                 │ - FastAPI endpoints │
│ - HTTP client   │                 │ - SQLite database   │
│ - Health check  │                 │ - Anomaly detection │
└─────────────────┘                 └─────────────────────┘
```

**Components:**
- **Central Platform**: FastAPI service for telemetry ingestion, anomaly detection using z-score analysis, and metrics reporting
- **Edge Node**: Autonomous agent that simulates and transmits telemetry data to the central platform
- **Anomaly Detection**: Real-time z-score based detection with configurable thresholds

## Prerequisites

- **Docker & Docker Compose** (recommended for quickstart)
- **Python 3.11+** (for local development)
- **Git** (for version control)

## Quick Start with Docker Compose

1. **Clone and configure**:
   ```bash
   git clone <repository-url>
   cd AIOps-EdgeBot-poc
   cp .env.example .env
   ```

2. **Start services**:
   ```bash
   docker-compose up --build
   ```
   
   Or use the convenience script:
   ```bash
   ./scripts/dev_up.sh
   ```

3. **Verify services**:
   - Central Platform: http://localhost:8000
   - Edge Node: http://localhost:8001  
   - OpenAPI Docs: http://localhost:8000/docs

4. **Monitor logs**:
   ```bash
   ./scripts/dev_logs.sh
   ```

5. **Stop services**:
   ```bash
   ./scripts/dev_down.sh
   ```

## API Examples

### Health Check
```bash
curl http://localhost:8000/healthz
# Response: {"status": "ok"}
```

### Ingest Telemetry
```bash
curl -X POST http://localhost:8000/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "edge_id": "edge-1",
    "ts": "2024-01-01T12:00:00Z",
    "metrics": {
      "cpu_percent": 75.5,
      "memory_percent": 60.0,
      "temperature": 45.0,
      "status": "healthy"
    }
  }'
```

### Get Service Metrics
```bash
curl http://localhost:8000/metrics
# Response: {
#   "ingested_count": 142,
#   "last_ingest_ts": "2024-01-01T12:05:30.123456"
# }
```

### Get Anomalies
```bash
curl http://localhost:8000/anomalies
# Response: {
#   "anomalies": [
#     {
#       "id": 1,
#       "edge_id": "edge-1",
#       "metric_name": "cpu_percent",
#       "metric_value": 95.2,
#       "z_score": 3.45,
#       "ts": "2024-01-01T12:03:00Z",
#       "detected_at": "2024-01-01T12:03:01.123456Z"
#     }
#   ],
#   "count": 1
# }
```

## Local Development (Virtual Environment)

### Setup Virtual Environment
```bash
make venv
source venv/bin/activate
```

### Run Central Platform Locally
```bash
cd central_platform
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Or use the Makefile:
```bash
make dev-central
```

### Run Edge Node Locally
```bash
cd edge_node
CENTRAL_API_BASE=http://localhost:8000 uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```

Or use the Makefile:
```bash
make dev-edge
```

## Testing and Quality

### Run Tests
```bash
make test
```

### Code Formatting and Linting
```bash
make fmt    # Format with black and isort
make lint   # Lint with flake8
```

### Generate Test Traffic
```bash
make seed
```

This sends a burst of telemetry data including anomalous values to test the detection system.

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `EDGE_ID` | `edge-1` | Unique identifier for edge node |
| `CENTRAL_API_BASE` | `http://central:8000` | Central platform API URL |
| `SEND_INTERVAL_SEC` | `5` | Telemetry transmission interval |
| `STANDALONE_MODE` | `false` | Run edge node without FastAPI server |

### Database

- **Type**: SQLite
- **Location**: `central_platform/data/central.db`
- **Auto-creation**: Tables are created automatically on startup
- **Models**: TelemetryRecord, AnomalyRecord

### Anomaly Detection

- **Algorithm**: Rolling z-score analysis
- **Window**: Last 10 values per metric per edge node
- **Threshold**: |z-score| >= 3.0
- **Metrics**: Only numeric values (int, float) are analyzed

## Makefile Commands

| Command | Description |
|---------|-------------|
| `make help` | Show available commands |
| `make venv` | Create Python virtual environment |
| `make fmt` | Format code (black, isort) |
| `make lint` | Lint code (flake8) |
| `make test` | Run pytest tests |
| `make up` | Start Docker services |
| `make down` | Stop Docker services |
| `make logs` | View service logs |
| `make seed` | Generate test traffic |
| `make clean` | Clean build artifacts |

## File Structure

```
AIOps-EdgeBot-poc/
├── central_platform/          # Central platform service
│   ├── app/
│   │   ├── main.py           # FastAPI application
│   │   ├── models.py         # SQLAlchemy models
│   │   └── schemas.py        # Pydantic schemas
│   ├── requirements.txt      # Python dependencies
│   ├── Dockerfile           # Container definition
│   └── data/                # SQLite database (runtime)
├── edge_node/               # Edge node agent
│   ├── app/
│   │   ├── main.py          # Edge node application
│   │   └── sim.py           # Telemetry simulator
│   ├── requirements.txt     # Python dependencies
│   └── Dockerfile          # Container definition
├── scripts/                 # Development scripts
│   ├── dev_up.sh           # Start development environment
│   ├── dev_down.sh         # Stop development environment
│   ├── dev_logs.sh         # View logs
│   └── seed_traffic.py     # Generate test data
├── tests/                   # Test suite
│   └── test_central_healthz.py
├── docker-compose.yml       # Service orchestration
├── .env.example            # Configuration template
├── Makefile               # Development automation
├── .pre-commit-config.yaml # Code quality hooks
└── README.md              # This file
```

## Troubleshooting

### Services Won't Start
```bash
# Check if ports are in use
lsof -i :8000
lsof -i :8001

# View detailed logs
docker-compose logs central
docker-compose logs edge
```

### Database Issues
```bash
# Reset database
rm -f central_platform/data/central.db*
docker-compose restart central
```

### Connection Issues
```bash
# Test central platform connectivity
curl http://localhost:8000/healthz

# Check edge node configuration
curl http://localhost:8001/config
```

### Development Environment
```bash
# Full reset
make clean
make up
```

## API Endpoints

### Central Platform (Port 8000)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/healthz` | Health check |
| POST | `/ingest` | Ingest telemetry from edge nodes |
| GET | `/anomalies` | Get recent anomalies |
| GET | `/metrics` | Get service metrics |
| GET | `/docs` | OpenAPI documentation |

### Edge Node (Port 8001)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/healthz` | Health check |
| GET | `/config` | Current configuration |
| GET | `/docs` | OpenAPI documentation |

## License

Apache License 2.0 - see [LICENSE](LICENSE) file for details.