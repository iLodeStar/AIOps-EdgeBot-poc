#!/bin/bash
# Development shutdown script

set -e

echo "Stopping EdgeBot POC development environment..."

# Stop services
docker compose down

echo "Services stopped successfully!"