# Full Regression Test Workflow

## Overview

The Full Regression Test workflow (`.github/workflows/regression-full.yml`) provides comprehensive end-to-end validation of the AIOps EdgeBot system, including:

- **Service Health**: Validates that all core services (EdgeBot, Mothership, Loki, TimescaleDB) can start and operate correctly
- **Data Pipeline**: Tests the complete EdgeBot → Mothership → [Loki + TimescaleDB] data flow
- **Dual-Sink Storage**: Verifies data is correctly written to both TimescaleDB and Loki sinks
- **Artifact Collection**: Gathers comprehensive logs, test reports, and query results for analysis

## When to Use

This workflow is designed for:
- **Manual execution** via GitHub Actions UI (workflow_dispatch trigger)
- **Comprehensive regression testing** before major releases
- **Integration validation** when making changes to data pipeline components
- **Performance analysis** using collected artifacts and metrics

## How to Run

### Via GitHub Actions UI

1. Navigate to the **Actions** tab in the GitHub repository
2. Select **"Full Regression Test"** from the workflow list
3. Click **"Run workflow"** 
4. Optionally specify a **Test ID Suffix** for easier identification
5. Click **"Run workflow"** to start execution

### Expected Runtime

- **Total Duration**: 15-25 minutes
- **Service Startup**: 2-3 minutes
- **E2E Tests**: 8-12 minutes  
- **Dual-Sink Validation**: 2-3 minutes
- **Artifact Collection**: 1-2 minutes

## Workflow Steps

### 1. Infrastructure Setup
- **Service Containers**: Starts TimescaleDB and Loki via GitHub Actions services
- **Dependencies**: Installs PostgreSQL client, Python packages, and testing tools
- **Health Checks**: Waits for all services to be ready before proceeding

### 2. Database Initialization
- **TimescaleDB Schema**: Creates the `events` hypertable with proper indexing
- **Health Validation**: Confirms database connectivity and schema creation

### 3. Cross-Phase E2E Testing
- **Existing Tests**: Runs `tests/e2e/test_cross_phase_integration.py`
- **Continue-on-Error**: Test failures don't stop artifact collection
- **Coverage**: EdgeBot → Mothership → Loki data flow validation

### 4. Mothership Dual-Sink Setup
- **Configuration**: Starts Mothership with both TSDB and Loki sinks enabled
- **Environment Variables**:
  ```bash
  MOTHERSHIP_DB_DSN=postgresql://postgres:postgres@localhost:5432/mothership
  LOKI_ENABLED=true
  LOKI_URL=http://localhost:3100
  TSDB_ENABLED=true
  ```

### 5. Test Batch Ingestion
- **Unique Test ID**: Generates timestamp-based identifier for deterministic validation
- **Test Data**: POSTs structured JSON batch with syslog and log events
- **Processing Delay**: Allows time for sink writes to complete

### 6. Dual-Sink Validation
- **Loki Query**: Searches for test events using query_range API
- **TimescaleDB Query**: Counts matching events using SQL
- **Failure Handling**: Workflow fails if data is not found in either sink

### 7. Artifact Collection
Comprehensive artifact upload including all logs, reports, and query results.

## Artifacts Generated

When the workflow completes, download the **`full-regression-reports`** artifact containing:

### Test Reports
- **`reports/e2e/report-e2e.html`**: Human-readable E2E test results
- **`reports/e2e/junit-e2e.xml`**: Machine-readable test results for CI integration
- **`reports/e2e/e2e-output.txt`**: Raw test execution output

### Data Validation Results  
- **`reports/ingest-response.json`**: Response from POST /ingest endpoint
- **`reports/loki-query.json`**: Loki query results containing test events
- **`reports/tsdb-count.txt`**: TimescaleDB event count for validation

### Service Logs
- **`reports/mothership-stdout.txt`**: Complete Mothership server logs
- **`reports/REGRESSION_SUMMARY.md`**: Generated summary with key metrics

## Interpreting Results

### Success Criteria
✅ **All checks pass** if:
- TimescaleDB and Loki services start successfully
- E2E tests execute (failures logged but don't fail the workflow)
- Mothership starts with dual-sink configuration
- Test batch is successfully posted to `/ingest`
- **Loki contains** at least one matching event
- **TimescaleDB contains** at least one matching event

### Failure Analysis
❌ **Workflow fails** if:
- Service containers fail to start (check service logs)
- Database schema initialization fails (check PostgreSQL connectivity)
- Mothership fails to start (check `mothership-stdout.txt`)
- Test batch POST returns error (check `ingest-response.json`)
- **Either sink** is missing the test data (check query results)

### Common Issues

1. **Service Startup Timeouts**
   - Services may take longer to start under load
   - Check GitHub Actions runner capacity and retry

2. **Database Connection Errors**
   - TimescaleDB container may be slow to accept connections
   - Review database initialization logs

3. **Network Connectivity**  
   - Loki may be unreachable from Mothership
   - Check service container networking configuration

4. **Data Sink Failures**
   - One sink succeeds but the other fails
   - Check individual sink health in `mothership-stdout.txt`

## Configuration Validation

The workflow validates these key configurations:

### TimescaleDB Setup
```sql
-- Events table with hypertable partitioning
CREATE TABLE events (
    ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    type TEXT NOT NULL,
    source TEXT NOT NULL, 
    data JSONB NOT NULL,
    id BIGSERIAL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 1-day chunk intervals for optimal performance
SELECT create_hypertable('events', 'ts', chunk_time_interval => INTERVAL '1 day');
```

### Loki Configuration
```yaml
# Mothership → Loki integration
loki:
  enabled: true
  url: http://localhost:3100
  timeout_sec: 10
  batch_size: 100
```

## Extending the Workflow

### Adding New Validation Steps
To add additional validation:

1. **Add new step** in the workflow after "Validate TimescaleDB contains test data"
2. **Generate artifacts** in the `reports/` directory  
3. **Update summary report** generation to include new validations
4. **Update artifact upload** to include new files

### Custom Test Data
To test with custom payloads:

1. **Modify TEST_BATCH** JSON in the "POST test batch" step
2. **Update validation queries** to match your custom data structure
3. **Adjust expected counts** in validation logic

### Additional Sinks
To add validation for new sinks:

1. **Add service container** (if needed) to workflow services section
2. **Update Mothership environment** variables to enable the new sink  
3. **Add validation step** with appropriate queries/checks
4. **Include results** in artifact collection

## Integration with CI/CD

While this workflow is manual-trigger only, it can be integrated with CI/CD pipelines:

### Automated Triggers
```yaml
# Example: trigger on release tags  
on:
  push:
    tags: ['v*']
  workflow_dispatch: # Keep manual option
```

### Status Checks
```yaml
# Use workflow results for branch protection
- name: Check Regression Status
  run: |
    if [ "${{ job.status }}" != "success" ]; then
      echo "❌ Full regression failed"
      exit 1
    fi
```

## Performance Benchmarks

Expected performance characteristics:

| Metric | Expected Value | Notes |
|--------|----------------|-------|
| **Service Startup** | < 3 minutes | TimescaleDB + Loki ready |
| **E2E Test Suite** | < 12 minutes | All cross-phase integration tests |
| **Batch Ingestion** | < 5 seconds | POST to /ingest with 2 events |
| **Sink Write Latency** | < 10 seconds | Data appears in both sinks |
| **Total Runtime** | < 25 minutes | Complete workflow execution |

Significant deviations from these benchmarks may indicate:
- Infrastructure performance issues
- Network connectivity problems  
- Code regressions affecting performance
- Resource contention in GitHub Actions runners

## Troubleshooting

### Debug Mode
For additional debugging, modify the workflow:

```yaml
# Add debug environment variables
env:
  LOG_LEVEL: DEBUG
  PYTHONDONTWRITEBYTECODE: 1
  PYTHONPATH: .
```

### Local Testing
Some components can be tested locally:

```bash
# Test configuration loading
cd mothership
export LOKI_ENABLED=true TSDB_ENABLED=true
python -c "from app.config import get_config; print(get_config().get_enabled_sinks())"

# Test E2E imports  
python -c "from tests.e2e.test_cross_phase_integration import TestCrossPhaseIntegration"
```

### Manual Validation
For manual verification of results:

```bash
# Check Loki manually
curl -s "http://localhost:3100/loki/api/v1/query_range?query={job=\"mothership\"}&start=2024-01-01T00:00:00Z&end=2024-12-31T23:59:59Z"

# Check TimescaleDB manually  
psql -h localhost -U postgres -d mothership -c "SELECT COUNT(*) FROM events;"
```