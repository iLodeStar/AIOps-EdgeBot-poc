#!/usr/bin/env python3
"""
CLI entry point for EdgeBot binary.
This module provides a clean entry point for PyInstaller.
"""
import sys
import os
from pathlib import Path

# Add the directory containing app modules to Python path
current_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(current_dir))

# Import and run the main function
try:
    from app.main import main

    if __name__ == "__main__":
        main()
except ImportError as e:
    print(f"Failed to import EdgeBot modules: {e}")
    sys.exit(1)
