# Makefile for AIOps EdgeBot - Unified Test Framework
# Provides standardized targets for testing, linting, and development

.PHONY: help install test test-unit test-e2e test-all coverage lint format clean docs-validate reports e2e-up e2e-down

# Default target
help:
	@echo "AIOps EdgeBot - Available Make targets:"
	@echo ""
	@echo "Setup and Dependencies:"
	@echo "  install          Install all dependencies (dev, edge_node, mothership)"
	@echo ""
	@echo "Testing:"
	@echo "  test            Run all tests (unit + e2e)"
	@echo "  test-unit       Run unit tests only"
	@echo "  test-e2e        Run end-to-end tests only"
	@echo "  test-parallel   Run tests with parallelization"
	@echo ""
	@echo "Code Quality:"
	@echo "  lint            Run linting (black --check)"
	@echo "  format          Format code with black"
	@echo "  coverage        Generate coverage report"
	@echo ""
	@echo "Documentation:"
	@echo "  docs-validate   Validate documentation links and references"
	@echo ""
	@echo "Reports:"
	@echo "  reports         Generate all test reports"
	@echo "  clean-reports   Clean report artifacts"
	@echo ""
	@echo "E2E Infrastructure:"
	@echo "  e2e-up          Start E2E testing infrastructure"
	@echo "  e2e-down        Stop E2E testing infrastructure"
	@echo "  e2e-logs        Show E2E service logs"
	@echo ""
	@echo "Maintenance:"
	@echo "  clean           Clean all temporary files and artifacts"

# Installation targets
install: install-dev install-edge install-mothership

install-dev:
	pip install -r requirements-dev.txt

install-edge:
	pip install -r edge_node/requirements.txt

install-mothership:
	pip install -r mothership/requirements.txt

# Testing targets
test: test-unit test-e2e

test-unit:
	@echo "Running unit tests..."
	@mkdir -p reports/unit
	cd edge_node && PYTHONPATH=. python -m pytest tests/ \
		-v --tb=short \
		--cov=app --cov-report=term-missing \
		--cov-report=xml:../reports/unit/coverage-edgebot.xml \
		--junitxml=../reports/unit/junit-edgebot.xml
	cd mothership && PYTHONPATH=. python -m pytest tests/ \
		-v --tb=short \
		--cov=app --cov-report=term-missing \
		--cov-report=xml:../reports/unit/coverage-mothership.xml \
		--junitxml=../reports/unit/junit-mothership.xml

test-e2e:
	@echo "Running end-to-end tests..."
	@mkdir -p reports/e2e
	PYTHONPATH=. python -m pytest tests/e2e/ \
		-v --tb=short \
		--junitxml=reports/e2e/junit-e2e.xml \
		--html=reports/e2e/report-e2e.html --self-contained-html

test-parallel:
	@echo "Running tests with parallelization..."
	@mkdir -p reports/parallel
	cd edge_node && PYTHONPATH=. python -m pytest tests/ -n auto \
		--cov=app --cov-report=xml:../reports/parallel/coverage-edgebot.xml \
		--junitxml=../reports/parallel/junit-edgebot.xml
	cd mothership && PYTHONPATH=. python -m pytest tests/ -n auto \
		--cov=app --cov-report=xml:../reports/parallel/coverage-mothership.xml \
		--junitxml=../reports/parallel/junit-mothership.xml
	PYTHONPATH=. python -m pytest tests/e2e/ -n auto \
		--junitxml=reports/parallel/junit-e2e.xml

test-all: install test

# Code quality targets
lint:
	@echo "Running linting checks..."
	black --check --diff edge_node/
	black --check --diff mothership/
	black --check --diff tests/

format:
	@echo "Formatting code..."
	black edge_node/
	black mothership/ 
	black tests/

# Coverage and reporting
coverage:
	@echo "Generating coverage report..."
	@mkdir -p reports/coverage
	cd edge_node && PYTHONPATH=. python -m pytest tests/ \
		--cov=app --cov-report=html:../reports/coverage/edgebot \
		--cov-report=xml:../reports/coverage/coverage-edgebot.xml
	cd mothership && PYTHONPATH=. python -m pytest tests/ \
		--cov=app --cov-report=html:../reports/coverage/mothership \
		--cov-report=xml:../reports/coverage/coverage-mothership.xml

reports: 
	@echo "Generating comprehensive test reports..."
	@mkdir -p reports/$(shell date +%Y%m%d-%H%M%S)
	bash scripts/run_tests.sh

# Documentation validation
docs-validate:
	@echo "Validating documentation..."
	python docs/validate_docs.py --check-links --check-references

# E2E Infrastructure management
e2e-up:
	@echo "Starting E2E testing infrastructure..."
	docker compose -f docker-compose.e2e.yml up -d loki
	@echo "Waiting for services to be ready..."
	@sleep 10
	@echo "E2E infrastructure ready!"

e2e-up-full:
	@echo "Starting full E2E testing stack..."
	docker compose -f docker-compose.e2e.yml --profile edgebot --profile mothership up -d
	@echo "Waiting for all services to be ready..."
	@sleep 20
	@echo "Full E2E stack ready!"

e2e-down:
	@echo "Stopping E2E testing infrastructure..."
	docker compose -f docker-compose.e2e.yml down -v

e2e-logs:
	@echo "E2E Service logs:"
	docker compose -f docker-compose.e2e.yml logs --tail=50

# Cleanup targets
clean: clean-reports clean-temp clean-docker

clean-reports:
	@echo "Cleaning report artifacts..."
	rm -rf reports/
	rm -rf .pytest_cache/
	rm -rf .coverage
	find . -name "htmlcov" -type d -exec rm -rf {} +
	find . -name "*.pyc" -delete
	find . -name "__pycache__" -type d -exec rm -rf {} +

clean-temp:
	@echo "Cleaning temporary files..."
	find . -name ".tmp*" -delete
	find . -name "tmp*" -type d -exec rm -rf {} +
	rm -rf /tmp/edgebot-e2e-*

clean-docker:
	@echo "Cleaning Docker E2E resources..."
	docker compose -f docker-compose.e2e.yml down -v --remove-orphans
	docker system prune -f --volumes

# Development helpers
dev-setup: install e2e-up
	@echo "Development environment ready!"
	@echo "- Loki available at: http://localhost:3100"
	@echo "- Run 'make test' to run all tests"
	@echo "- Run 'make e2e-down' when finished"

# Health check
health-check:
	@echo "Checking service health..."
	@curl -s -f http://localhost:3100/ready && echo "✓ Loki is healthy" || echo "✗ Loki is not responding"
	@curl -s -f http://localhost:8081/healthz && echo "✓ EdgeBot is healthy" || echo "✗ EdgeBot is not responding"  
	@curl -s -f http://localhost:8443/healthz && echo "✓ Mothership is healthy" || echo "✗ Mothership is not responding"