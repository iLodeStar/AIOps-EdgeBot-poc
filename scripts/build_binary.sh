#!/bin/bash
set -e

# EdgeBot Binary Build Script
# Builds a single-file executable using PyInstaller

echo "EdgeBot Binary Build Script"
echo "=========================="

# Check if we're in the right directory
if [ ! -f "edge_node/app/main.py" ]; then
    echo "Error: Must run from repository root"
    exit 1
fi

# Create virtual environment if it doesn't exist
VENV_DIR="build-venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
fi

# Activate virtual environment
echo "Activating virtual environment..."
source "$VENV_DIR/bin/activate"

# Upgrade pip
python -m pip install --upgrade pip

# Install dependencies
echo "Installing dependencies..."
cd edge_node

# Use shorter timeout and retry strategy
echo "Installing requirements with timeout protection..."
if ! timeout 120 pip install --timeout 30 -r requirements.txt; then
    echo "Regular install failed, trying with essential packages only..."
    # Try installing only essential packages for build
    pip install --no-deps pyinstaller click pyyaml structlog httpx aiofiles uvloop || exit 1
fi

# Install PyInstaller
echo "Installing PyInstaller..."
if ! pip install --timeout 30 pyinstaller; then
    echo "PyInstaller install failed"
    exit 1
fi

# Clean previous build artifacts
echo "Cleaning previous builds..."
rm -rf build dist __pycache__

# Run PyInstaller with reproducible flags
echo "Building binary with PyInstaller..."
pyinstaller \
    --clean \
    --noconfirm \
    edgebot.spec

# Verify binary was created
if [ ! -f "dist/edgebot" ]; then
    echo "Error: Binary not created!"
    exit 1
fi

# Make binary executable
chmod +x dist/edgebot

# Get binary size
BINARY_SIZE=$(ls -lh dist/edgebot | awk '{print $5}')
echo "Binary created successfully!"
echo "Location: dist/edgebot"
echo "Size: $BINARY_SIZE"

# Test the binary
echo "Testing binary..."
if ./dist/edgebot --help > /dev/null; then
    echo "Binary test successful!"
else
    echo "Warning: Binary test failed"
    exit 1
fi

echo "Build complete!"