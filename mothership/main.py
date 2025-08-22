#!/usr/bin/env python3
"""
Mothership Server Entry Point

Simple entry point for the EdgeBot mothership data collection server.
"""

if __name__ == "__main__":
    import uvicorn
    import structlog
    import os
    
    # Configure structured logging
    structlog.configure(
        processors=[
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer() if os.getenv("LOG_FORMAT") != "json" 
            else structlog.processors.JSONRenderer()
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    
    from app.config import get_config
    
    config = get_config()
    
    print(f"""
EdgeBot Mothership Starting
===========================
Host: {config.server.host}:{config.server.port}
Enabled sinks: {', '.join(config.get_enabled_sinks())}

Endpoints:
- POST /ingest   - Receive data from EdgeBot nodes
- GET  /health   - Health check including sink status
- GET  /         - Basic server information

Environment Variables:
- LOKI_ENABLED={os.getenv('LOKI_ENABLED', 'false')}
- TSDB_ENABLED={os.getenv('TSDB_ENABLED', 'true')}
- LOKI_URL={os.getenv('LOKI_URL', 'http://localhost:3100')}
""")
    
    uvicorn.run(
        "app.server:app",
        host=config.server.host,
        port=config.server.port,
        log_level=config.log_level.lower(),
        access_log=True,
        reload=os.getenv("DEV_MODE", "false").lower() == "true"
    )