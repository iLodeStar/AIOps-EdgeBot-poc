# AIOps EdgeBot v0.4 Services

This directory contains the v0.4 service stack for AIOps EdgeBot, providing advanced analytics and fleet management capabilities.

## Services Overview

### 1. Capacity Forecasting Service (`capacity-forecasting/`)
**Purpose**: Predicts system capacity needs based on historical data and trends
- **Port**: 8080
- **Health Check**: `GET /healthz`
- **Main Endpoint**: `POST /forecast`
- **Use Case**: Proactive resource planning and scaling decisions

### 2. Fleet Aggregation Service (`fleet-aggregation/`)  
**Purpose**: Aggregates and correlates data from multiple EdgeBot nodes across a fleet
- **Port**: 8080  
- **Health Check**: `GET /healthz`
- **Main Endpoint**: `POST /aggregate`
- **Use Case**: Fleet-wide monitoring and anomaly detection

### 3. Cross-Ship Benchmarking Service (`cross-ship-benchmarking/`)
**Purpose**: Compares performance metrics across different ships/nodes for optimization  
- **Port**: 8080
- **Health Check**: `GET /healthz` 
- **Main Endpoint**: `POST /benchmark`
- **Use Case**: Performance optimization and best practice identification

## Build and Dependency Fixes

### Issue Resolution
This v0.4 release fixes the following build issues:

1. **Fixed NATS Dependency**: 
   - ❌ Old: `asyncio-nats-client==2.6.0` (package doesn't exist)
   - ✅ New: `nats-py==2.6.0` (correct maintained package)

2. **Fixed Python 3.12 Compatibility**:
   - ❌ Old: Python 3.12 with old scientific packages (no wheels available)
   - ✅ New: Python 3.11 base image with compatible package versions

3. **Optimized Dependencies**:
   - All services use the same tested dependency versions
   - `--only-binary=all` flag in Dockerfiles for faster builds
   - Non-root user execution for security

### Dependencies Used
```txt
fastapi==0.104.1          # Web framework
uvicorn[standard]==0.24.0  # ASGI server
pydantic==2.4.2           # Data validation
clickhouse-driver==0.2.6  # Database connectivity
requests==2.31.0          # HTTP client
nats-py==2.6.0            # NATS messaging (fixed from asyncio-nats-client)
numpy==1.24.3             # Scientific computing
pandas==2.0.3             # Data manipulation
scikit-learn==1.3.0       # Machine learning
statsmodels==0.14.0       # Statistical analysis
python-dateutil==2.8.2    # Date utilities
```

## Quick Start

### Build All Services
```bash
# Build capacity forecasting
cd services/capacity-forecasting
docker build -t capacity-forecasting:0.4.0 .

# Build fleet aggregation  
cd ../fleet-aggregation
docker build -t fleet-aggregation:0.4.0 .

# Build cross-ship benchmarking
cd ../cross-ship-benchmarking  
docker build -t cross-ship-benchmarking:0.4.0 .
```

### Run Services
```bash
# Start capacity forecasting service
docker run -d -p 8081:8080 --name capacity-forecasting capacity-forecasting:0.4.0

# Start fleet aggregation service  
docker run -d -p 8082:8080 --name fleet-aggregation fleet-aggregation:0.4.0

# Start benchmarking service
docker run -d -p 8083:8080 --name cross-ship-benchmarking cross-ship-benchmarking:0.4.0
```

### Health Checks
```bash
# Check all services
curl -f http://localhost:8081/healthz  # Capacity forecasting
curl -f http://localhost:8082/healthz  # Fleet aggregation  
curl -f http://localhost:8083/healthz  # Cross-ship benchmarking
```

## Usage Examples

### Capacity Forecasting
```bash
curl -X POST http://localhost:8081/forecast \
  -H "Content-Type: application/json" \
  -d '{
    "metrics": [
      {"timestamp": "2024-01-01T12:00:00Z", "cpu_usage": 75.2, "memory_usage": 68.5}
    ],
    "forecast_horizon_days": 7
  }'
```

### Fleet Aggregation
```bash
curl -X POST http://localhost:8082/aggregate \
  -H "Content-Type: application/json" \
  -d '{
    "nodes": [
      {
        "node_id": "edge-001", 
        "location": "pacific-fleet",
        "last_seen": "2024-01-01T12:00:00Z",
        "metrics": {"cpu_usage": 72.3, "events_processed": 1500}
      }
    ],
    "aggregation_type": "summary"
  }'
```

### Cross-Ship Benchmarking
```bash
curl -X POST http://localhost:8083/benchmark \
  -H "Content-Type: application/json" \
  -d '{
    "ships": [
      {
        "ship_id": "SS-MERIDIAN-001",
        "ship_name": "Meridian Explorer", 
        "metrics": {"performance_score": 92.1, "efficiency_rating": 87.5},
        "timestamp": "2024-01-01T12:00:00Z"
      }
    ],
    "benchmark_type": "performance"
  }'
```

## Service Integration

### With EdgeBot Core
These services are designed to work with the core EdgeBot system:

```yaml
# Add to docker-compose.yml
services:
  capacity-forecasting:
    build: ./services/capacity-forecasting
    ports:
      - "8081:8080"
    environment:
      - NATS_URL=nats://nats:4222
      
  fleet-aggregation:
    build: ./services/fleet-aggregation  
    ports:
      - "8082:8080"
    environment:
      - NATS_URL=nats://nats:4222
      
  cross-ship-benchmarking:
    build: ./services/cross-ship-benchmarking
    ports:
      - "8083:8080"
    environment:
      - NATS_URL=nats://nats:4222
```

### Service Communication
Services communicate via:
- **NATS messaging** for real-time data exchange
- **HTTP APIs** for request/response operations  
- **Shared data stores** (ClickHouse, TimescaleDB) for historical data

## Troubleshooting

### Build Issues
```bash
# If you see "asyncio-nats-client not found"
# ✅ Fixed: Updated to nats-py==2.6.0

# If you see "no matching wheel for Python 3.12"  
# ✅ Fixed: Using Python 3.11 base images

# If build is slow
# ✅ Optimized: Using --only-binary=all flag
```

### Runtime Issues  
```bash
# Check service logs
docker logs capacity-forecasting
docker logs fleet-aggregation
docker logs cross-ship-benchmarking

# Check service health
curl -f http://localhost:8081/healthz
curl -f http://localhost:8082/healthz  
curl -f http://localhost:8083/healthz
```

### Development
```bash
# Run services locally for development
cd services/capacity-forecasting
pip install -r requirements.txt
python main.py

# Service will start on http://localhost:8080
# API docs available at http://localhost:8080/docs
```

## Production Deployment

### Resource Requirements
- **Minimum per service**: 1 CPU core, 2GB RAM
- **Recommended per service**: 2+ CPU cores, 4+ GB RAM
- **Storage**: Shared access to EdgeBot data stores

### Monitoring
Each service exposes:
- **Health endpoint**: `/healthz` for uptime monitoring
- **Metrics endpoint**: `/metrics` for Prometheus integration  
- **API documentation**: `/docs` (FastAPI auto-generated)

### Scaling
Services are stateless and can be horizontally scaled:
```bash
# Scale capacity forecasting to 3 replicas
docker service scale capacity-forecasting=3
```

## Next Steps

1. **Integration**: Connect services to live EdgeBot data streams
2. **ML Models**: Replace mock forecasting with trained models  
3. **Alerting**: Add threshold-based alerts for anomalies
4. **Dashboard**: Create Grafana dashboards for service metrics
5. **Performance**: Optimize for high-volume data processing

For more information, see:
- [Main README](../../README.md) 
- [Optional Services Guide](../../docs/OPTIONAL_SERVICES.md)
- [Architecture Documentation](../../docs/ARCHITECTURE.md)