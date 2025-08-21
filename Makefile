.PHONY: help venv fmt lint test up down logs seed validate demo clean

# Default target
help:
	@echo "EdgeBot POC Development Commands"
	@echo "================================"
	@echo "make venv      - Create Python virtual environment"
	@echo "make fmt       - Format code with black and isort"
	@echo "make lint      - Lint code with flake8"
	@echo "make test      - Run tests with pytest"
	@echo "make up        - Start services with Docker Compose"
	@echo "make down      - Stop services"
	@echo "make logs      - View service logs"
	@echo "make seed      - Generate seed traffic for testing"
	@echo "make validate  - Validate POC implementation"
	@echo "make demo      - Show system overview and sample data"
	@echo "make clean     - Clean up build artifacts and containers"

venv:
	@echo "Creating Python virtual environment..."
	python3 -m venv venv
	./venv/bin/pip install --upgrade pip
	./venv/bin/pip install -r central_platform/requirements.txt
	./venv/bin/pip install -r edge_node/requirements.txt
	./venv/bin/pip install black isort flake8 pytest
	@echo "Virtual environment created. Activate with: source venv/bin/activate"

fmt:
	@echo "Formatting code..."
	black central_platform/app/ edge_node/app/ tests/ scripts/ --line-length 88
	isort central_platform/app/ edge_node/app/ tests/ scripts/ --profile black

lint:
	@echo "Linting code..."
	flake8 central_platform/app/ edge_node/app/ tests/ scripts/ --max-line-length=88 --extend-ignore=E203,W503

test:
	@echo "Running tests..."
	python -m pytest tests/ -v

up:
	@echo "Starting services..."
	./scripts/dev_up.sh

down:
	@echo "Stopping services..."
	./scripts/dev_down.sh

logs:
	@echo "Viewing logs..."
	./scripts/dev_logs.sh

seed:
	@echo "Generating seed traffic..."
	python scripts/seed_traffic.py

validate:
	@echo "Validating EdgeBot POC implementation..."
	python scripts/validate.py

demo:
	@echo "Showing EdgeBot POC overview..."
	python scripts/demo.py

clean:
	@echo "Cleaning up..."
	docker compose down --volumes --remove-orphans
	docker system prune -f
	rm -rf central_platform/data/*.db*
	rm -rf venv/
	rm -rf **/__pycache__/
	rm -rf **/*.pyc

# Local development targets
dev-central:
	@echo "Running central platform locally..."
	cd central_platform && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

dev-edge:
	@echo "Running edge node locally..."
	cd edge_node && CENTRAL_API_BASE=http://localhost:8000 python -m uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload