#!/usr/bin/env python3
"""
EdgeBot POC Demo - Shows sample telemetry data and system overview
"""

import json
import sys
import os
from datetime import datetime, timezone

# Add current directory to path
sys.path.insert(0, '.')

def show_architecture():
    """Display the architecture overview"""
    print("🏗️  EdgeBot POC Architecture")
    print("=" * 50)
    print("""
┌─────────────────┐    HTTP/JSON    ┌─────────────────────┐
│   Edge Node     │ ──────────────→ │  Central Platform   │
│   (Port 8001)   │    telemetry    │      (Port 8000)    │
│                 │                 │                     │
│ - Telemetry sim │                 │ - FastAPI endpoints │
│ - HTTP client   │                 │ - SQLite database   │
│ - Health check  │                 │ - Anomaly detection │
└─────────────────┘                 └─────────────────────┘

Components:
• Central Platform: FastAPI service with /healthz, /ingest, /metrics, /anomalies
• Edge Node: Autonomous agent sending telemetry every 5 seconds
• Anomaly Detection: Z-score analysis with threshold |z| >= 3.0
• Database: SQLite with TelemetryRecord and AnomalyRecord tables
""")


def show_sample_telemetry():
    """Generate and display sample telemetry data"""
    print("\n📊 Sample Telemetry Data")
    print("=" * 50)
    
    try:
        from edge_node.app.sim import TelemetrySimulator, create_telemetry_data
        
        # Generate data from different edge nodes
        edge_nodes = ['edge-1', 'edge-2', 'edge-production']
        
        for edge_id in edge_nodes:
            print(f"\n🔹 {edge_id}:")
            
            # Generate a few data points
            for i in range(2):
                telemetry = create_telemetry_data(edge_id)
                
                # Pretty print the JSON
                formatted_json = json.dumps(telemetry, indent=2)
                print(f"   {formatted_json}")
                
                if i == 0:  # Only show details for first one
                    metrics = telemetry['metrics']
                    print(f"   → CPU: {metrics['cpu_percent']:.1f}%")
                    print(f"   → Memory: {metrics['memory_percent']:.1f}%")
                    print(f"   → Temperature: {metrics['temperature']:.1f}°C")
                    print(f"   → Network Latency: {metrics['network_latency_ms']:.1f}ms")
                    print(f"   → Status: {metrics['status']}")
                
                print()
            
    except ImportError as e:
        print(f"❌ Could not import telemetry simulation: {e}")


def show_api_endpoints():
    """Show available API endpoints"""
    print("\n🌐 API Endpoints")
    print("=" * 50)
    
    endpoints = [
        ("GET /healthz", "Health check", '{"status": "ok"}'),
        ("POST /ingest", "Ingest telemetry", "Accepts telemetry JSON data"),
        ("GET /metrics", "Service metrics", '{"ingested_count": 142, "last_ingest_ts": "..."}'),
        ("GET /anomalies", "Recent anomalies", "List of detected anomalies with z-scores"),
        ("GET /docs", "OpenAPI docs", "Interactive API documentation"),
    ]
    
    print("Central Platform (http://localhost:8000):")
    for method_path, description, example in endpoints:
        print(f"  {method_path:<15} - {description}")
        if len(example) < 50:
            print(f"                    Example: {example}")
        else:
            print(f"                    {example}")
    
    print("\nEdge Node (http://localhost:8001):")
    edge_endpoints = [
        ("GET /healthz", "Health check", '{"status": "ok", "edge_id": "edge-1", ...}'),
        ("GET /config", "Current config", "Shows edge node configuration"),
        ("GET /docs", "OpenAPI docs", "Interactive API documentation"),
    ]
    
    for method_path, description, example in edge_endpoints:
        print(f"  {method_path:<15} - {description}")
        print(f"                    Example: {example}")


def show_quickstart():
    """Show quickstart commands"""
    print("\n🚀 Quick Start Commands")
    print("=" * 50)
    
    commands = [
        ("Start services", "make up", "Starts both central platform and edge node"),
        ("View logs", "make logs", "Follow logs from all services"),
        ("Test endpoints", "curl http://localhost:8000/healthz", "Simple health check"),
        ("Generate test data", "make seed", "Send burst of test telemetry"),
        ("Stop services", "make down", "Stop all services"),
        ("Clean up", "make clean", "Remove containers and data"),
    ]
    
    for description, command, notes in commands:
        print(f"{description:<20}: {command}")
        print(f"                      {notes}")
        print()


def main():
    """Main demo function"""
    print("🤖 EdgeBot POC - AIOps Edge Telemetry & Anomaly Detection")
    print("Version: 1.0.0")
    print("Repository: iLodeStar/AIOps-EdgeBot-poc")
    
    # Change to repository root if needed
    if os.path.exists('central_platform'):
        os.chdir('.')
    elif os.path.exists('../central_platform'):
        os.chdir('..')
    else:
        print("\n❌ Cannot find EdgeBot POC repository structure")
        print("Make sure you're in the repository root directory.")
        sys.exit(1)
    
    show_architecture()
    show_sample_telemetry()
    show_api_endpoints()
    show_quickstart()
    
    print("=" * 70)
    print("💡 Ready to start? Run: make up")
    print("📖 Full documentation: README.md")
    print("🔧 All commands: make help")


if __name__ == "__main__":
    main()