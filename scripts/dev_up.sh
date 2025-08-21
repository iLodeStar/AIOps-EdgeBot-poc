#!/bin/bash
# Development startup script

set -e

echo "Starting EdgeBot POC development environment..."

# Copy .env.example to .env if it doesn't exist
if [ ! -f .env ]; then
    echo "Creating .env from .env.example..."
    cp .env.example .env
fi

# Start services with docker-compose
echo "Starting services with Docker Compose..."
docker compose up --build -d

echo "Services started successfully!"
echo ""
echo "Central Platform: http://localhost:8000"
echo "Edge Node:        http://localhost:8001"
echo "OpenAPI Docs:     http://localhost:8000/docs"
echo ""
echo "Use './scripts/dev_logs.sh' to view logs"
echo "Use './scripts/dev_down.sh' to stop services"