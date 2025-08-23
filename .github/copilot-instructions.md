# AIOps EdgeBot Copilot Instructions

**Always follow these instructions first and fallback to search or bash commands only when you encounter unexpected information that does not match the info here.**

## Overview

AIOps EdgeBot is a lightweight edge data collector and shipper built in Python. It collects logs and metrics from various sources (syslog, SNMP, weather API, file tailing, NMEA, network flows) and ships them to a mothership server or saves them locally. The project includes both the EdgeBot node (`edge_node/`) and a data collection server called Mothership (`mothership/`).

## Working Effectively

### Bootstrap and Build Commands (NEVER CANCEL - Critical Timing Info)

**NEVER CANCEL builds or long-running commands. Build may take 45-60+ minutes. Use long timeouts.**

1. **Install all dependencies** (takes ~7 minutes total):
   ```bash
   pip install -r requirements-dev.txt               # ~3 minutes
   pip install -r edge_node/requirements.txt         # ~2 minutes  
   pip install -r mothership/requirements.txt        # ~2 minutes
   ```

2. **Run tests** (takes ~8 seconds - NEVER CANCEL, timeout 30+ minutes):
   ```bash
   mkdir -p reports
   pytest -q --maxfail=1 --disable-warnings \
     --cov=edge_node/app --cov-report=term-missing --cov-report=xml:coverage.xml \
     --junitxml=reports/junit.xml \
     --html=reports/report.html --self-contained-html
   ```

3. **Generate test report**:
   ```bash
   python scripts/simple_test_report.py reports/junit.xml > reports/simple_report.md
   ```

4. **Linting** (takes ~0.2 seconds):
   ```bash
   black --version
   black --check edge_node    # Many files need formatting currently
   black --check mothership
   ```

5. **Format code** (if needed):
   ```bash
   black edge_node
   black mothership
   ```

6. **Build binary** (NEVER CANCEL - takes 45-60+ minutes, timeout 90+ minutes):
   ```bash
   bash scripts/build_binary.sh
   ```
   **WARNING**: Binary build may fail due to network timeout issues with PyPI. If it fails, document the failure but do not attempt alternatives unless specifically needed.

### Additional Useful Tools

1. **Built-in test script** (sends sample syslog messages):
   ```bash
   cd edge_node && python send_test_syslog.py
   ```

2. **Data import tools** (for sample data):
   ```bash
   cd edge_node && python tools/import_jsonl_events.py --help
   cd edge_node && python tools/import_weather_csv.py --help
   ```

3. **Version check**:
   ```bash
   cd edge_node && python -m app.main --version
   ```

### Running Applications

#### EdgeBot (Primary Application)

1. **Setup configuration**:
   ```bash
   cd edge_node
   cp config.example.yaml config.yaml
   ```

2. **Dry run validation** (always test configuration first):
   ```bash
   python -m app.main --dry-run
   ```

3. **Run EdgeBot**:
   ```bash
   python -m app.main -c config.yaml
   ```

4. **Health endpoints** (EdgeBot must be running):
   - Health check: `curl -f http://localhost:8081/healthz`
   - Metrics: `curl -s http://localhost:8081/metrics | head -20`
   
5. **Test syslog functionality**:
   ```bash
   # Send test syslog message
   echo "<34>Aug 23 12:05:45 testhost testapp: Test message" | nc -u -w1 localhost 5514
   
   # Check output files
   ls -la edge_node/data/out/
   cat edge_node/data/out/payload-*.json
   ```

#### Mothership Server

**WARNING**: Mothership requires PostgreSQL database and has configuration issues in main.py. The simpler uvicorn approach may not work due to database dependencies.

1. **Setup configuration**:
   ```bash
   cd mothership
   cp config.example.yaml config.yaml
   ```

2. **Attempt to run** (will likely fail without database):
   ```bash
   # This will fail without PostgreSQL database
   export TSDB_ENABLED=false
   export LOKI_ENABLED=false
   python -m uvicorn app.server:app --host 0.0.0.0 --port 8443 --log-level info
   ```

## Docker Deployment

### EdgeBot Docker Compose

```bash
cd edge_node
cp config.example.yaml config.yaml
cp .env.example .env
mkdir -p data/out data/logs
docker compose up -d --build
```

**Health checks**:
```bash
curl -f http://localhost:8081/healthz
docker logs -f edgebot
ls -l data/out
```

### One-Click Deployment

For complete deployment with Docker:
```bash
curl -fsSL https://raw.githubusercontent.com/iLodeStar/AIOps-EdgeBot-poc/main/deploy.sh | bash
```

## Validation and Testing

### ALWAYS Test After Changes

1. **Run dry-run validation**:
   ```bash
   cd edge_node && python -m app.main --dry-run
   ```

2. **Complete end-to-end validation workflow**:
   ```bash
   # Clean any existing processes
   pkill -f "python -m app.main" || true
   sleep 2
   
   # Navigate to edge_node directory
   cd edge_node
   
   # Start EdgeBot in background
   python -m app.main -c config.yaml &
   EDGEBOT_PID=$!
   
   # Wait for startup (5 seconds)
   sleep 5
   
   # Test health endpoint
   curl -f http://localhost:8081/healthz && echo "✅ Health check passed"
   
   # Test using built-in test script
   python send_test_syslog.py
   
   # Verify output files generated
   ls -la data/out/ && echo "✅ Output files created"
   
   # Test metrics endpoint  
   curl -s http://localhost:8081/metrics | head -5
   
   # Stop EdgeBot cleanly
   kill $EDGEBOT_PID
   wait $EDGEBOT_PID 2>/dev/null || true
   ```

3. **Alternative manual syslog test**:
   ```bash
   # Send test syslog message manually (from edge_node directory)
   echo "<34>$(date '+%b %d %H:%M:%S') testhost testapp: Test validation message" | nc -u -w1 localhost 5514
   
   # Check latest output file
   ls -t data/out/payload-*.json | head -1 | xargs cat
   ```

4. **Always run tests and linting**:
   ```bash
   pytest -q --maxfail=1 --disable-warnings --cov=edge_node/app
   black --check edge_node
   ```

### Known Issues

1. **One failing test**: `mothership.tests.test_llm.TestLLMEnricher::test_circuit_breaker` - asyncio event loop issue
2. **Binary build timeouts**: Network connectivity issues with PyPI cause timeouts
3. **Mothership configuration**: main.py has missing server field, requires PostgreSQL database
4. **Code formatting**: 28 files need black formatting
5. **No database provided**: Mothership cannot run without PostgreSQL setup

## Common File Locations

### Repository Structure
```
edge_node/                 # Main EdgeBot application
├── app/                  # Application source code
│   ├── main.py          # Entry point with supervision
│   ├── config.py        # Configuration management
│   ├── inputs/          # Data collection modules
│   └── output/          # Data shipping
├── config.yaml          # Configuration file
├── requirements.txt     # Python dependencies
├── Dockerfile          # Container build
└── docker-compose.yaml # Easy deployment

mothership/               # Data collection server
├── app/                 # Server application code
│   ├── config.py       # Configuration management
│   ├── server.py       # FastAPI server
│   └── storage/        # Storage backends
├── tests/              # Test suite
└── requirements.txt    # Server dependencies

docs/                    # Documentation
├── TESTING.md          # Testing instructions
├── DEPLOYMENT.md       # Deployment guide
├── ARCHITECTURE.md     # System design
└── USER_GUIDE.md       # Usage guide
```

### Key Configuration Files

- `edge_node/config.yaml` - Main EdgeBot configuration
- `edge_node/.env` - Environment variables
- `mothership/config.yaml` - Mothership server config
- `.github/workflows/ci.yml` - CI pipeline configuration

### Common Commands Output

```bash
# Repository root contents
$ ls -la
.github/         docs/           mothership/
.gitignore       edge_node/      prometheus/
LICENSE          grafana/        promtail/
README.md        requirements-dev.txt
alertmanager/    scripts/
compose.observability.yml
demo.sh          deploy.sh

# EdgeBot app structure  
$ ls -la edge_node/app/
config.py    inputs/     main.py     output/

# Test and report artifacts
$ ls -la reports/
junit.xml           # Machine-readable test results
report.html         # Full HTML test report
simple_report.md    # Non-technical summary
```

## Environment Requirements

- **Python**: 3.10+ (tested with 3.12.3)
- **Operating System**: Linux (Ubuntu/Debian preferred)
- **Network**: Outbound internet access for dependencies
- **Ports**: 
  - 5514/udp, 5515/tcp (syslog input)
  - 8081 (health/metrics)
  - 8080 (main service)
- **Optional**: Docker for containerized deployment
- **Optional**: PostgreSQL for Mothership server

## Troubleshooting

### Common Issues

1. **Import errors**: Ensure you're in the correct directory and dependencies are installed
2. **Permission denied**: Use `chmod +x` on scripts, check file permissions
3. **Port already in use**: Check for running services with `netstat -tlnp | grep 8081`
4. **Config validation fails**: Use `--dry-run` to debug configuration issues
5. **Network timeouts**: Binary builds may timeout, document rather than retry
6. **Database connection**: Mothership requires PostgreSQL, use Docker compose for full setup

### Recovery Commands

```bash
# Reset EdgeBot data
rm -rf edge_node/data/out/*

# Kill hanging processes
pkill -f "python -m app.main"

# Clean build artifacts
rm -rf build-venv/ edge_node/dist/ edge_node/build/

# Check service status
curl -f http://localhost:8081/healthz || echo "EdgeBot not running"
```

## Development Workflow

1. **Always validate first**: Run `--dry-run` before making changes
2. **Test early**: Run tests immediately after any configuration or code changes  
3. **Format code**: Use `black` to format Python code before committing
4. **Check health**: Always verify health endpoints after starting services
5. **Validate data flow**: Send test messages and verify output files are generated
6. **Use timeouts**: Set 60+ minute timeouts for build commands, 30+ minutes for tests

Remember: This is a distributed system with network dependencies. Always test the complete data flow from input (syslog) through processing to output (files or mothership) to ensure changes work end-to-end.