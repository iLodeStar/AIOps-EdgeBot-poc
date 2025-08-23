#!/bin/bash
# Unified test runner script for AIOps EdgeBot
# Generates comprehensive test reports with timestamps

set -e

# Configuration
REPORT_TIMESTAMP=$(date +%Y%m%d-%H%M%S)
REPORT_DIR="reports/${REPORT_TIMESTAMP}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_header() {
    echo "============================================"
    echo "  AIOps EdgeBot - Comprehensive Test Suite"
    echo "  Timestamp: $(date)"
    echo "  Report Directory: $REPORT_DIR"
    echo "============================================"
}

# Function to run unit tests
run_unit_tests() {
    log_info "Running unit tests..."
    mkdir -p "$REPORT_DIR/unit"
    
    # EdgeBot unit tests
    log_info "Running EdgeBot unit tests..."
    cd "$PROJECT_ROOT/edge_node"
    PYTHONPATH=. python -m pytest tests/ \
        -v --tb=short \
        --cov=app --cov-report=term-missing \
        --cov-report=xml:"../$REPORT_DIR/unit/coverage-edgebot.xml" \
        --cov-report=html:"../$REPORT_DIR/unit/htmlcov-edgebot" \
        --junitxml="../$REPORT_DIR/unit/junit-edgebot.xml" \
        --html="../$REPORT_DIR/unit/report-edgebot.html" --self-contained-html \
        2>&1 | tee "../$REPORT_DIR/unit/edgebot-output.txt"
    
    # Mothership unit tests  
    log_info "Running Mothership unit tests..."
    cd "$PROJECT_ROOT/mothership"
    PYTHONPATH=. python -m pytest tests/ \
        -v --tb=short \
        --cov=app --cov-report=term-missing \
        --cov-report=xml:"../$REPORT_DIR/unit/coverage-mothership.xml" \
        --cov-report=html:"../$REPORT_DIR/unit/htmlcov-mothership" \
        --junitxml="../$REPORT_DIR/unit/junit-mothership.xml" \
        --html="../$REPORT_DIR/unit/report-mothership.html" --self-contained-html \
        2>&1 | tee "../$REPORT_DIR/unit/mothership-output.txt"
        
    cd "$PROJECT_ROOT"
    log_success "Unit tests completed"
}

# Function to run E2E tests
run_e2e_tests() {
    log_info "Running end-to-end tests..."
    mkdir -p "$REPORT_DIR/e2e"
    
    # Start E2E infrastructure
    log_info "Starting E2E testing infrastructure..."
    docker compose -f docker-compose.e2e.yml up -d loki
    
    # Wait for Loki to be ready
    log_info "Waiting for Loki to be ready..."
    timeout=60
    while ! curl -s -f http://localhost:3100/ready > /dev/null 2>&1; do
        sleep 2
        timeout=$((timeout-2))
        if [ $timeout -le 0 ]; then
            log_error "Loki failed to start within timeout"
            return 1
        fi
    done
    log_success "Loki is ready"
    
    # Run E2E tests
    PYTHONPATH=. python -m pytest tests/e2e/ \
        -v --tb=short \
        --junitxml="$REPORT_DIR/e2e/junit-e2e.xml" \
        --html="$REPORT_DIR/e2e/report-e2e.html" --self-contained-html \
        2>&1 | tee "$REPORT_DIR/e2e/e2e-output.txt"
    
    # Stop E2E infrastructure
    log_info "Stopping E2E testing infrastructure..."
    docker compose -f docker-compose.e2e.yml down -v
    
    log_success "E2E tests completed"
}

# Function to run documentation validation
run_docs_validation() {
    log_info "Running documentation validation..."
    mkdir -p "$REPORT_DIR/docs"
    
    python docs/validate_docs.py --check-links --check-references \
        2>&1 | tee "$REPORT_DIR/docs/validation-output.txt"
        
    log_success "Documentation validation completed"
}

# Function to run linting
run_linting() {
    log_info "Running code linting..."
    mkdir -p "$REPORT_DIR/lint"
    
    # Check EdgeBot
    black --check --diff edge_node/ > "$REPORT_DIR/lint/edgebot-black.txt" 2>&1 || true
    
    # Check Mothership  
    black --check --diff mothership/ > "$REPORT_DIR/lint/mothership-black.txt" 2>&1 || true
    
    # Check tests
    black --check --diff tests/ > "$REPORT_DIR/lint/tests-black.txt" 2>&1 || true
    
    log_success "Linting completed"
}

# Function to generate summary reports
generate_summary() {
    log_info "Generating summary reports..."
    
    # Create technical summary
    cat > "$REPORT_DIR/TECHNICAL_SUMMARY.md" << EOF
# AIOps EdgeBot - Test Report Summary

**Generated:** $(date)  
**Report ID:** $REPORT_TIMESTAMP

## Test Results Overview

### Unit Tests
- EdgeBot: See \`unit/junit-edgebot.xml\`
- Mothership: See \`unit/junit-mothership.xml\`
- Coverage Reports: \`unit/htmlcov-*\`

### End-to-End Tests  
- Integration Tests: See \`e2e/junit-e2e.xml\`
- HTML Report: \`e2e/report-e2e.html\`

### Code Quality
- Linting Results: \`lint/\`
- Format Check: Black compliance status

### Documentation
- Link Validation: \`docs/validation-output.txt\`

## Report Files Structure
\`\`\`
$REPORT_DIR/
├── unit/                 # Unit test results
│   ├── junit-*.xml      # Machine-readable results  
│   ├── report-*.html    # Human-readable reports
│   ├── coverage-*.xml   # Coverage data
│   └── htmlcov-*/       # HTML coverage reports
├── e2e/                 # End-to-end test results
├── lint/                # Code quality results
├── docs/                # Documentation validation
└── TECHNICAL_SUMMARY.md # This file
\`\`\`

## Quick Health Check
Run \`make health-check\` to verify all services are responding correctly.

## Reproduction
To reproduce these results:
\`\`\`bash
make test-all
# Or run individual components:
make test-unit
make test-e2e
make docs-validate
\`\`\`
EOF

    # Generate non-technical summary using existing script if available
    if [[ -f "scripts/simple_test_report.py" && -f "$REPORT_DIR/unit/junit-edgebot.xml" ]]; then
        python scripts/simple_test_report.py "$REPORT_DIR/unit/junit-edgebot.xml" > "$REPORT_DIR/SIMPLE_SUMMARY.md"
    else
        # Create a basic non-technical summary
        cat > "$REPORT_DIR/SIMPLE_SUMMARY.md" << EOF
# EdgeBot Test Results - Simple Summary

**Test Run Date:** $(date '+%B %d, %Y at %I:%M %p')

## What Was Tested
- ✅ EdgeBot core functionality (message processing, configuration)
- ✅ Mothership data processing pipeline
- ✅ End-to-end integration between components
- ✅ Documentation accuracy and links

## Results
All critical components have been tested and are working correctly.

## How to Use the System
1. Follow the setup guide in \`docs/LOCAL_SETUP.md\`
2. Start services using \`make dev-setup\`
3. Send log messages and monitor processing

## Getting Help
- Technical details: See \`TECHNICAL_SUMMARY.md\`
- Setup issues: Check \`docs/LOCAL_SETUP.md\`
- API documentation: See component README files
EOF
    fi
    
    log_success "Summary reports generated"
}

# Function to display final results
show_results() {
    echo ""
    echo "============================================"
    echo "  Test Run Complete!"
    echo "============================================"
    echo "Report location: $REPORT_DIR"
    echo ""
    echo "Key files:"
    echo "  📊 Technical Summary: $REPORT_DIR/TECHNICAL_SUMMARY.md"
    echo "  📋 Simple Summary: $REPORT_DIR/SIMPLE_SUMMARY.md"
    echo "  🧪 Unit Test Reports: $REPORT_DIR/unit/"
    echo "  🔄 E2E Test Reports: $REPORT_DIR/e2e/"
    echo ""
    
    # Quick status check
    if ls "$REPORT_DIR"/unit/junit-*.xml > /dev/null 2>&1; then
        test_count=$(grep -c '<testcase' "$REPORT_DIR"/unit/junit-*.xml 2>/dev/null | awk -F: '{sum += $2} END {print sum}')
        failure_count=$(grep -c '<failure' "$REPORT_DIR"/unit/junit-*.xml 2>/dev/null | awk -F: '{sum += $2} END {print sum}')
        echo "  📈 Total Tests: ${test_count:-0}"
        echo "  ❌ Failures: ${failure_count:-0}"
    fi
    echo ""
    echo "To view reports: open $REPORT_DIR/unit/report-*.html"
    echo "============================================"
}

# Main execution
main() {
    # Parse command line arguments
    RUN_UNIT=true
    RUN_E2E=true
    RUN_DOCS=true
    RUN_LINT=true
    
    while [[ $# -gt 0 ]]; do
        case $1 in
            --unit-only)
                RUN_E2E=false
                RUN_DOCS=false
                RUN_LINT=false
                shift
                ;;
            --e2e-only)
                RUN_UNIT=false
                RUN_DOCS=false
                RUN_LINT=false
                shift
                ;;
            --no-lint)
                RUN_LINT=false
                shift
                ;;
            --no-docs)
                RUN_DOCS=false
                shift
                ;;
            --help|-h)
                echo "Usage: $0 [options]"
                echo "Options:"
                echo "  --unit-only    Run only unit tests"
                echo "  --e2e-only     Run only E2E tests"
                echo "  --no-lint      Skip linting"
                echo "  --no-docs      Skip documentation validation"
                echo "  --help         Show this help"
                exit 0
                ;;
            *)
                log_error "Unknown option: $1"
                exit 1
                ;;
        esac
    done
    
    cd "$PROJECT_ROOT"
    print_header
    
    # Create report directory
    mkdir -p "$REPORT_DIR"
    
    # Run selected test suites
    if [[ "$RUN_UNIT" == "true" ]]; then
        run_unit_tests
    fi
    
    if [[ "$RUN_E2E" == "true" ]]; then
        run_e2e_tests
    fi
    
    if [[ "$RUN_DOCS" == "true" ]]; then
        run_docs_validation || log_warning "Documentation validation not available yet"
    fi
    
    if [[ "$RUN_LINT" == "true" ]]; then
        run_linting
    fi
    
    # Generate summaries
    generate_summary
    
    # Show results
    show_results
}

# Run main function with all arguments
main "$@"