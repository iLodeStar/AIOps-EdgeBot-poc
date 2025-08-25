# AIOps EdgeBot - Local Setup Guide

This guide provides step-by-step instructions to set up, configure, and run the AIOps EdgeBot system on your local development environment.

## Prerequisites

### System Requirements
- **Operating System**: Linux (Ubuntu 20.04+ recommended) or macOS
- **Python**: Version 3.11 or higher
- **Memory**: Minimum 4GB RAM (8GB recommended)
- **Disk Space**: 2GB free space
- **Network**: Outbound internet access for dependencies

### Required Software

#### 1. Docker & Docker Compose
```bash
# Ubuntu/Debian
sudo apt update
sudo apt install docker.io docker-compose-plugin
sudo usermod -aG docker $USER
newgrp docker

# macOS (using Homebrew)
brew install docker docker-compose
```

#### 2. Python 3.11+
```bash
# Ubuntu/Debian
sudo apt install python3.11 python3.11-venv python3.11-dev
sudo apt install python3-pip

# macOS  
brew install python@3.11
```

#### 3. Git
```bash
# Ubuntu/Debian
sudo apt install git

# macOS
brew install git
```

#### 4. Additional Tools
```bash
# Ubuntu/Debian
sudo apt install curl wget netcat-openbsd

# macOS
brew install curl wget netcat
```

## Installation Steps

### Step 1: Clone the Repository

```bash
git clone https://github.com/iLodeStar/AIOps-EdgeBot-poc.git
cd AIOps-EdgeBot-poc
```

### Step 2: Set Up Python Environment

```bash
# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate

# Upgrade pip
pip install --upgrade pip

# Install all dependencies
make install
# Or manually:
# pip install -r requirements-dev.txt
# pip install -r edge_node/requirements.txt  
# pip install -r mothership/requirements.txt
```

### Step 3: Verify Installation

```bash
# Check Python packages
pip list | grep pytest
pip list | grep fastapi

# Verify tools are available
docker --version
docker compose version
python --version
```

## Configuration

### Step 1: Environment Setup

```bash
# Copy example environment files
cp .env.example .env
cp edge_node/.env.example edge_node/.env

# Edit configuration as needed
nano .env
```

### Step 2: EdgeBot Configuration

```bash
# Copy and customize EdgeBot config
cp edge_node/config.example.yaml edge_node/config.yaml

# Edit EdgeBot configuration
nano edge_node/config.yaml
```

**Key EdgeBot Settings:**
```yaml
server:
  host: '127.0.0.1'
  port: 8080

inputs:
  syslog:
    enabled: true
    udp_port: 5514
    tcp_port: 5515

output:
  # For standalone testing (file output)
  file:
    enabled: true
    dir: './data/out'
  
  # For integration with Mothership  
  mothership:
    url: 'http://localhost:8443/ingest'
    batch_size: 10
    flush_interval_sec: 30

observability:
  health_port: 8081
  metrics_enabled: true
```

### Step 3: Mothership Configuration

```bash
# Copy and customize Mothership config
cp mothership/config.example.yaml mothership/config.yaml

# Edit Mothership configuration  
nano mothership/config.yaml
```

**Key Mothership Settings:**
```yaml
server:
  host: '0.0.0.0'
  port: 8443

sinks:
  loki:
    enabled: true
    url: 'http://localhost:3100'
  tsdb:
    enabled: false  # Disable for simple setup

pipeline:
  processors:
    - type: 'drop_fields'
      config:
        fields: ['_internal']
    - type: 'add_tags'
      config:
        add_tags:
          source: 'local-setup'
```

## Starting the System

### Option A: Quick Start (Recommended for Beginners)

```bash
# Start observability stack first
make e2e-up
# This starts Loki and waits for it to be ready

# In separate terminals:

# Terminal 1: Start Mothership
cd mothership
PYTHONPATH=. python -m app.server --host 0.0.0.0 --port 8443

# Terminal 2: Start EdgeBot  
cd edge_node
PYTHONPATH=. python -m app.main -c config.yaml

# Terminal 3: Monitor logs (optional)
docker logs -f edgebot-e2e-loki-1
```

### Option B: Full Development Setup

```bash
# Use the development helper
make dev-setup

# This will:
# 1. Install all dependencies
# 2. Start Loki
# 3. Print helpful information
```

### Option C: Step-by-Step Manual Setup

#### 1. Start Observability Infrastructure

```bash
# Start only Loki for log storage
docker compose -f docker-compose.e2e.yml up -d loki

# Wait for Loki to be ready
until curl -s http://localhost:3100/ready > /dev/null; do
  echo "Waiting for Loki to be ready..."
  sleep 2
done
echo "✅ Loki is ready!"
```

#### 2. Start Mothership

```bash
cd mothership

# Set environment variables
export LOKI_ENABLED=true
export LOKI_URL=http://localhost:3100
export TSDB_ENABLED=false
export MOTHERSHIP_LLM_ENABLED=false

# Start Mothership
PYTHONPATH=. python -m app.server --host 0.0.0.0 --port 8443
```

#### 3. Start EdgeBot

```bash
# In a new terminal
cd edge_node

# Start EdgeBot
PYTHONPATH=. python -m app.main -c config.yaml
```

## Verification & Testing

### Step 1: Health Checks

```bash
# Check EdgeBot health
curl -f http://localhost:8081/healthz
# Should return: {"status": "healthy", ...}

# Check Mothership health  
curl -f http://localhost:8443/healthz
# Should return: {"status": "healthy", "sinks": {"loki": {"enabled": true, "healthy": true}}}

# Check Loki
curl -f http://localhost:3100/ready
# Should return: ready
```

### Step 2: Send Test Data

#### Option A: Use Built-in Test Script
```bash
cd edge_node
python send_test_syslog.py
```

#### Option B: Send Manual Syslog Messages
```bash
# Send test syslog via UDP
echo "<34>$(date '+%b %d %H:%M:%S') testhost testapp: Hello from local setup!" | nc -u -w1 localhost 5514

# Send test syslog via TCP
echo "<34>$(date '+%b %d %H:%M:%S') testhost testapp: TCP test message!" | nc -w1 localhost 5515
```

#### Option C: Use the E2E Test Suite
```bash
# Run comprehensive tests
make test-e2e

# Run specific test scenarios
python -m pytest tests/e2e/test_edgebot_standalone.py -v
```

### Step 3: Verify Data Flow

#### Check EdgeBot Output Files (if using file output)
```bash
cd edge_node
ls -la data/out/
cat data/out/payload-*.json
```

#### Check Loki for Stored Logs
```bash
# Query Loki via API
curl -s "http://localhost:3100/loki/api/v1/query?query={job=\"edgebot\"}" | jq .

# Or use Grafana (if started with --profile debug)
# Open http://localhost:3000 (admin/admin)
```

#### Check Metrics
```bash
# EdgeBot metrics
curl -s http://localhost:8081/metrics | grep edgebot_

# Mothership metrics
curl -s http://localhost:8443/metrics | grep mothership_

# Mothership detailed stats
curl -s http://localhost:8443/stats | jq .
```

## Optional: Enable Advanced Features

### Quick Start for Optional Services

For a comprehensive guide to enabling and using optional services, see **[docs/OPTIONAL_SERVICES.md](OPTIONAL_SERVICES.md)**

**Quick Enable Options:**
```bash
# Enable observability stack (Grafana + Prometheus + Loki)
docker compose -f compose.observability.yml up -d

# Enable local LLM processing
docker compose up -d ollama
docker compose exec ollama ollama pull llama3.1:8b-instruct-q4_0

# Health check all services
curl -f http://localhost:8081/healthz  # EdgeBot
curl -f http://localhost:3000/api/health  # Grafana  
curl -f http://localhost:11434/api/tags  # Ollama
```

**Service Dashboard Links:**
- EdgeBot: [http://localhost:8081/healthz](http://localhost:8081/healthz)
- Grafana: [http://localhost:3000](http://localhost:3000) (admin/admin)
- Prometheus: [http://localhost:9090](http://localhost:9090)
- Ollama: [http://localhost:11434](http://localhost:11434)

### LLM Offline Processing

If you want to enable LLM features (requires additional setup):

```bash
# Install and start Ollama
curl -fsSL https://ollama.ai/install.sh | sh
ollama serve &
ollama pull llama2:7b

# Configure Mothership for LLM
export MOTHERSHIP_LLM_ENABLED=true
export MOTHERSHIP_LLM_MODEL=ollama
export OLLAMA_BASE_URL=http://localhost:11434

# Restart Mothership with LLM enabled
```

See `docs/LLM_OFFLINE.md` for complete LLM setup instructions.

### Full Observability Stack

```bash
# Start with Grafana for visualization
docker compose -f compose.observability.yml up -d

# Access services:
# - Grafana: http://localhost:3000 (admin/admin)
# - Prometheus: http://localhost:9090  
# - Loki: http://localhost:3100
# - AlertManager: http://localhost:9093
```

## Usage Examples

### Example 1: Local Syslog Collection

```bash
# Configure your local rsyslog to forward to EdgeBot
echo '*.* @@127.0.0.1:5514' | sudo tee -a /etc/rsyslog.conf
sudo systemctl restart rsyslog

# Generate test logs
logger -p local0.info "Test message from local rsyslog"

# Check EdgeBot received it
curl -s http://localhost:8081/metrics | grep messages_received
```

### Example 2: Weather Data Collection

Edit `edge_node/config.yaml`:
```yaml
inputs:
  weather:
    enabled: true
    api_key: "your-api-key"  # Get from OpenWeatherMap
    locations:
      - city: "San Francisco"
        country: "US"
    interval_minutes: 15
```

### Example 3: File Monitoring

```yaml
inputs:
  file_tailer:
    enabled: true
    paths:
      - "/var/log/application.log"
      - "/tmp/test.log" 
    from_beginning: false
```

## Troubleshooting

### Common Issues

#### Port Conflicts
```bash
# Check which process is using a port
sudo netstat -tlnp | grep :8080
# Or
sudo lsof -i :8080

# Kill process if needed
sudo kill -9 <PID>
```

#### Permission Issues
```bash
# Fix Docker permissions
sudo usermod -aG docker $USER
newgrp docker

# Fix log directory permissions  
sudo chown -R $USER:$USER edge_node/data/
```

#### Module Import Errors
```bash
# Ensure PYTHONPATH is set correctly
export PYTHONPATH=$(pwd)/edge_node:$(pwd)/mothership:$PYTHONPATH

# Or use make targets which handle this automatically
make test-unit
```

#### Service Not Starting
```bash
# Check configuration syntax
cd edge_node
python -m app.main -c config.yaml --dry-run

cd mothership  
python -c "import yaml; yaml.safe_load(open('config.yaml'))"

# Check logs
docker compose -f docker-compose.e2e.yml logs loki
```

### Log Locations

```bash
# EdgeBot logs (if running manually)
cd edge_node && PYTHONPATH=. python -m app.main -c config.yaml > edgebot.log 2>&1 &

# Mothership logs
cd mothership && PYTHONPATH=. python -m app.server > mothership.log 2>&1 &

# Docker service logs
docker compose -f docker-compose.e2e.yml logs -f loki
```

### Getting Help

1. **Check service health endpoints first**: `curl http://localhost:8081/healthz`
2. **Review configuration files**: Ensure YAML syntax is correct
3. **Check network connectivity**: `telnet localhost 5514`
4. **Run tests for validation**: `make test-unit`
5. **Check GitHub issues**: Look for similar problems
6. **Enable debug logging**: Set `LOG_LEVEL=DEBUG` in environment

## Performance Tuning

### For High Volume Environments

```yaml
# EdgeBot optimizations
output:
  mothership:
    batch_size: 100        # Larger batches
    flush_interval_sec: 10 # More frequent flushes

# Mothership optimizations  
sinks:
  loki:
    batch_size: 1000       # Larger Loki batches
    timeout_sec: 30        # Longer timeouts
```

### Resource Limits

```bash
# Monitor resource usage
htop
docker stats

# Set Python process limits if needed  
ulimit -v 1048576  # 1GB virtual memory limit
```

## Next Steps

Once you have the system running locally:

1. **Explore the APIs**: Try the `/stats` and `/metrics` endpoints
2. **Run the test suite**: `make test-all` 
3. **Deploy to containers**: Use `docker-compose.e2e.yml` as a base
4. **Configure monitoring**: Set up Grafana dashboards
5. **Scale testing**: Run with higher message volumes
6. **Explore integrations**: Try SNMP, weather, or file monitoring

For production deployment, see:
- `docs/DEPLOYMENT.md` - Production deployment guide
- `docs/DEPLOY_K8S.md` - Kubernetes deployment
- `docs/OBSERVABILITY.md` - Monitoring and alerting setup