#!/bin/bash
# Development logs viewer script

set -e

echo "Showing EdgeBot POC logs..."
echo "Press Ctrl+C to exit"

# Follow logs for all services
docker compose logs -f