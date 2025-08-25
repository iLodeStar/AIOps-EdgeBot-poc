# Optional Services Guide - Beginner Friendly

This guide provides step-by-step instructions for enabling, configuring, and using optional services in the AIOps EdgeBot system.

## Quick Reference

### Service Status Dashboard
| Service | Status | Dashboard URL | Default Port |
|---------|---------|---------------|--------------|
| **EdgeBot Health** | Core | [http://localhost:8081/healthz](http://localhost:8081/healthz) | 8081 |
| **EdgeBot Metrics** | Core | [http://localhost:8081/metrics](http://localhost:8081/metrics) | 8081 |
| **Mothership** | Core | [http://localhost:8443](http://localhost:8443) | 8443 |
| **Grafana** | Optional | [http://localhost:3000](http://localhost:3000) | 3000 |
| **Prometheus** | Optional | [http://localhost:9090](http://localhost:9090) | 9090 |
| **AlertManager** | Optional | [http://localhost:9093](http://localhost:9093) | 9093 |
| **Loki** | Optional | [http://localhost:3100](http://localhost:3100) | 3100 |
| **Ollama LLM** | Optional | [http://localhost:11434](http://localhost:11434) | 11434 |

## Optional Services Overview

### 1. **Ollama** (Local LLM Runtime)
**Purpose**: Offline AI-powered log enrichment and analysis
- **When to use**: For intelligent log analysis without external API dependencies
- **Resource requirements**: 4+ CPU cores, 8+ GB RAM
- **Best for**: Production edge deployments, air-gapped environments

### 2. **Observability Stack** (Grafana + Prometheus + Loki)
**Purpose**: Advanced monitoring, alerting, and log visualization
- **When to use**: Production monitoring, debugging, performance analysis
- **Resource requirements**: 2+ CPU cores, 4+ GB RAM
- **Best for**: Operations teams, troubleshooting

### 3. **Vector Database** (Future: Qdrant)
**Purpose**: Semantic search and similarity matching of events
- **Status**: Planned for future releases
- **When to use**: Advanced analytics, pattern detection

### 4. **Stream Processing** (Future: Benthos)
**Purpose**: Real-time event correlation and incident creation
- **Status**: Planned for future releases  
- **When to use**: Complex event processing, automated incident management

## Quick Start Guides

### Enable/Disable Optional Services

#### Option A: Using Environment Variables
```bash
# Copy and edit environment file
cp .env.example .env

# Edit .env file to enable desired services
ENABLE_OBSERVABILITY=true     # Grafana + Prometheus + Loki
ENABLE_OLLAMA=false          # Local LLM processing
ENABLE_ALERTING=false        # Email alerts via Alertmanager
```

#### Option B: Using Docker Compose Profiles
```bash
# Start core services only (default)
docker compose up -d

# Start with observability stack
docker compose --profile observability up -d

# Start everything
docker compose --profile observability --profile llm up -d
```

#### Option C: Manual Service Control
```bash
# Start individual services
docker compose up -d grafana prometheus loki
docker compose up -d ollama

# Stop services
docker compose stop grafana prometheus loki
docker compose stop ollama
```

## Service-Specific Setup

### 1. Ollama (Local LLM) Setup

#### Quick Enable
```bash
# Method 1: Environment variable
export MOTHERSHIP_LLM_ENABLED=true
export LLM_BACKEND=ollama

# Method 2: Docker compose
docker compose up -d ollama
```

#### Recommended Model Download
```bash
# Connect to Ollama container
docker compose exec ollama bash

# Download recommended model (5GB)
ollama pull llama3.1:8b-instruct-q4_0

# Alternative smaller model (3GB) 
ollama pull phi3:3.8b-mini-instruct-q4_0

# List available models
ollama list
```

#### Health Check
```bash
# Test Ollama API
curl -f http://localhost:11434/api/tags

# Test model inference
curl -X POST http://localhost:11434/api/generate \
  -H "Content-Type: application/json" \
  -d '{
    "model": "llama3.1:8b-instruct-q4_0",
    "prompt": "Hello world",
    "stream": false
  }'
```

#### Configuration
Add to your mothership `config.yaml`:
```yaml
llm:
  enabled: true
  backend: ollama
  ollama_base_url: "http://localhost:11434"
  ollama_model: "llama3.1:8b-instruct-q4_0"
  confidence_threshold: 0.8
  max_tokens: 150
```

#### Usage Test
```bash
# Send test log for LLM enrichment
curl -X POST http://localhost:8443/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "events": [{
      "message": "Failed login attempt for user admin from 192.168.1.100",
      "type": "auth",
      "timestamp": "2024-01-01T12:00:00Z"
    }]
  }'
```

---

### 2. Observability Stack Setup

#### Quick Enable
```bash
# Start full observability stack
docker compose -f compose.observability.yml up -d

# Or using profiles
docker compose --profile observability up -d
```

#### Access Services
- **Grafana**: [http://localhost:3000](http://localhost:3000) (admin/admin)
- **Prometheus**: [http://localhost:9090](http://localhost:9090)
- **Loki**: [http://localhost:3100](http://localhost:3100)
- **AlertManager**: [http://localhost:9093](http://localhost:9093)

#### Health Checks
```bash
# Check all services
curl -f http://localhost:3000/api/health     # Grafana
curl -f http://localhost:9090/-/healthy      # Prometheus  
curl -f http://localhost:3100/ready          # Loki
curl -f http://localhost:9093/-/healthy      # AlertManager
```

#### Configuration for Log Shipping
Add to your mothership `config.yaml`:
```yaml
sinks:
  loki:
    enabled: true
    url: "http://localhost:3100"
    batch_size: 100
    timeout_sec: 30
```

Enable via environment:
```bash
export LOKI_ENABLED=true
export LOKI_URL=http://localhost:3100
```

#### Usage Test
```bash
# Send test logs
curl -X POST http://localhost:8443/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "events": [{
      "message": "Test log for Loki",
      "level": "info",
      "timestamp": "2024-01-01T12:00:00Z"
    }]
  }'

# Query logs in Loki
curl -G "http://localhost:3100/loki/api/v1/query_range" \
  --data-urlencode 'query={level="info"}' \
  --data-urlencode 'limit=10'
```

---

### 3. Email Alerting Setup

#### Quick Enable  
```bash
# Copy environment template
cp .env.example .env

# Edit .env with your email settings
nano .env
```

#### Email Configuration
Add to `.env` file:
```bash
# SMTP settings
ALERT_SMTP_HOST=smtp.gmail.com
ALERT_SMTP_PORT=587
ALERT_SMTP_USER=your-email@gmail.com
ALERT_SMTP_PASS=your-app-password
ALERT_SMTP_STARTTLS=true

# Email routing
ALERT_EMAIL_FROM=edgebot-alerts@yourcompany.com
ALERT_EMAIL_TO=ops-team@yourcompany.com,admin@yourcompany.com
```

#### Health Check
```bash
# Test alert manager config
docker compose exec alertmanager amtool config show

# Send test alert
curl -X POST http://localhost:9093/api/v1/alerts \
  -H "Content-Type: application/json" \
  -d '[{
    "labels": {
      "alertname": "TestAlert",
      "severity": "info"
    },
    "annotations": {
      "summary": "This is a test alert"
    }
  }]'
```

## Proper Start Order

### For Development
```bash
# 1. Start core data services
docker compose up -d

# 2. Verify core health
curl -f http://localhost:8081/healthz

# 3. Start optional observability (if needed)
docker compose -f compose.observability.yml up -d

# 4. Start LLM services (if needed) 
docker compose up -d ollama
docker compose exec ollama ollama pull llama3.1:8b-instruct-q4_0
```

### For Production
```bash
# 1. Infrastructure services
docker compose up -d loki prometheus

# 2. Core application services
docker compose up -d edgebot mothership

# 3. Monitoring and alerting
docker compose up -d grafana alertmanager

# 4. AI/ML services (after core is stable)
docker compose up -d ollama

# 5. Verify all health endpoints
make health-check  # Or manual curl commands
```

### Service Dependencies
```
Core Services:
  EdgeBot → Mothership → (Loki OR TimescaleDB)

Optional Services:
  Grafana → (Prometheus AND Loki)
  AlertManager → Prometheus
  Ollama → (standalone, no dependencies)
  
Health Check Order:
  1. EdgeBot (:8081/healthz)
  2. Mothership (:8443/healthz) 
  3. Loki (:3100/ready)
  4. Prometheus (:9090/-/healthy)
  5. Grafana (:3000/api/health)
```

## Troubleshooting

### Docker Build Failures

#### Common Issue: Python Dependency Conflicts
```bash
# Error: Could not find a version that satisfies the requirement asyncio-nats-client==2.6.0
# Solution: This package doesn't exist, use nats-py instead

# Fix for scientific Python packages on Python 3.12
# Use Python 3.11 base images instead:
FROM python:3.11-slim

# Or update to compatible versions:
# numpy>=1.26.0 (for Python 3.12 support)
# pandas>=2.1.0 (for Python 3.12 support)
```

#### Docker Daemon Connection Issues
```bash
# Error: Cannot connect to Docker daemon
sudo systemctl start docker
sudo usermod -aG docker $USER
newgrp docker

# Or check Docker Desktop is running (macOS/Windows)
```

#### Build Context Too Large
```bash
# Error: Build context too large  
# Add to .dockerignore:
node_modules/
__pycache__/
*.pyc
.git/
```

### Service Health Issues

#### EdgeBot Not Starting
```bash
# Check configuration
cd edge_node
python -m app.main -c config.yaml --dry-run

# Check port availability
sudo netstat -tlnp | grep :8081

# Check logs
docker compose logs edgebot
```

#### Ollama Model Loading Issues  
```bash
# Error: Model not found
docker compose exec ollama ollama list
docker compose exec ollama ollama pull llama3.1:8b-instruct-q4_0

# Error: Out of memory
# Use smaller model:
docker compose exec ollama ollama pull phi3:3.8b-mini-instruct-q4_0

# Or increase Docker memory limit in Docker Desktop
```

#### Grafana Dashboard Empty
```bash
# Check data source connection
curl -f http://localhost:9090/api/v1/status/config  # Prometheus
curl -f http://localhost:3100/ready                 # Loki

# Check if logs are being sent
curl -f http://localhost:8443/stats | jq .pipeline.events_processed
```

### Port Conflicts
```bash
# Find what's using a port
sudo lsof -i :3000    # Grafana
sudo lsof -i :9090    # Prometheus
sudo lsof -i :11434   # Ollama

# Kill conflicting process
sudo kill -9 <PID>

# Or use different ports in docker-compose.yml
```

### Configuration Validation
```bash
# Validate YAML syntax
python -c "import yaml; yaml.safe_load(open('config.yaml'))"

# Test environment variables
env | grep -E "(LOKI|OLLAMA|ALERT)"

# Test service connectivity
curl -f http://localhost:8081/healthz && echo "✅ EdgeBot OK"
curl -f http://localhost:8443/healthz && echo "✅ Mothership OK"
curl -f http://localhost:3000/api/health && echo "✅ Grafana OK"
```

## Getting Help

### Health Check Script
Create a quick health check script:
```bash
#!/bin/bash
# save as check-health.sh

echo "=== AIOps EdgeBot Health Check ==="
echo

echo "Core Services:"
curl -f http://localhost:8081/healthz 2>/dev/null && echo "✅ EdgeBot" || echo "❌ EdgeBot"
curl -f http://localhost:8443/healthz 2>/dev/null && echo "✅ Mothership" || echo "❌ Mothership"

echo
echo "Optional Services:"
curl -f http://localhost:3000/api/health 2>/dev/null && echo "✅ Grafana" || echo "❌ Grafana (optional)"
curl -f http://localhost:9090/-/healthy 2>/dev/null && echo "✅ Prometheus" || echo "❌ Prometheus (optional)"
curl -f http://localhost:3100/ready 2>/dev/null && echo "✅ Loki" || echo "❌ Loki (optional)"
curl -f http://localhost:11434/api/tags 2>/dev/null && echo "✅ Ollama" || echo "❌ Ollama (optional)"

echo
echo "=== Service URLs ==="
echo "EdgeBot Health: http://localhost:8081/healthz"
echo "EdgeBot Metrics: http://localhost:8081/metrics"
echo "Mothership API: http://localhost:8443"
echo "Grafana Dashboard: http://localhost:3000 (admin/admin)"
echo "Prometheus: http://localhost:9090"
echo "Loki: http://localhost:3100"
echo "Ollama: http://localhost:11434"
```

### Support Resources

1. **Documentation Links**:
   - [Architecture Overview](docs/ARCHITECTURE.md)
   - [Local Setup Guide](docs/LOCAL_SETUP.md)
   - [LLM Offline Setup](docs/LLM_OFFLINE.md)
   - [Observability Guide](docs/OBSERVABILITY.md)

2. **Quick Links**:
   - [Ollama Model Library](https://ollama.com/library)
   - [Grafana Dashboard Repository](https://grafana.com/grafana/dashboards/)
   - [Prometheus Configuration](https://prometheus.io/docs/prometheus/latest/configuration/configuration/)

3. **Getting Help**:
   - Check the [GitHub Issues](https://github.com/iLodeStar/AIOps-EdgeBot-poc/issues) for similar problems
   - Run `make test-unit` to validate your environment
   - Enable debug logging: `LOG_LEVEL=DEBUG`
   - Check Docker logs: `docker compose logs -f <service-name>`

4. **Community**:
   - Report issues with service setup on GitHub
   - Include output of `check-health.sh` in issue reports
   - Specify your environment (OS, Docker version, available RAM)

---

## What's Next?

Once you have optional services running:

1. **Explore the Features**:
   - Try log enrichment with Ollama LLM
   - Create custom Grafana dashboards
   - Set up email alerts for critical events

2. **Scale Your Setup**:
   - Review performance tuning in [docs/LOCAL_SETUP.md](docs/LOCAL_SETUP.md)
   - Consider production deployment with [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)

3. **Advanced Configuration**:
   - Custom model fine-tuning for log analysis
   - Multi-environment monitoring setups
   - Integration with external systems

The optional services provide powerful capabilities while maintaining the core EdgeBot functionality. Start with what you need and expand gradually!