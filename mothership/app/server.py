"""FastAPI server for the mothership with data ingestion and health endpoints."""

import asyncio
import gzip
import json
from typing import Dict, Any, List
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException, Response, status
from fastapi.responses import JSONResponse
import structlog

from .config import get_config, AppConfig
from .storage import SinksManager

logger = structlog.get_logger(__name__)

# Global state
app_config: AppConfig = None
sinks_manager: SinksManager = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager for startup/shutdown."""
    global app_config, sinks_manager
    
    # Startup
    logger.info("Starting mothership server")
    
    app_config = get_config()
    sinks_manager = SinksManager(app_config)
    await sinks_manager.start()
    
    logger.info("Mothership server started successfully",
               enabled_sinks=app_config.get_enabled_sinks())
    
    yield
    
    # Shutdown
    logger.info("Shutting down mothership server")
    if sinks_manager:
        await sinks_manager.stop()
    logger.info("Mothership server shutdown complete")


app = FastAPI(
    title="EdgeBot Mothership",
    description="Data collection and storage service for EdgeBot telemetry",
    version="1.0.0",
    lifespan=lifespan
)


@app.post("/ingest")
async def ingest_data(request: Request) -> JSONResponse:
    """Ingest data from EdgeBot nodes."""
    try:
        # Handle gzip-compressed content
        body = await request.body()
        if request.headers.get("content-encoding") == "gzip":
            body = gzip.decompress(body)
        
        # Parse JSON payload
        try:
            payload = json.loads(body.decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.warning("Invalid JSON payload", error=str(e))
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid JSON payload"
            )
        
        # Validate payload structure
        if not isinstance(payload, dict):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Payload must be a JSON object"
            )
        
        messages = payload.get("messages", [])
        if not isinstance(messages, list):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Messages must be an array"
            )
        
        if not messages:
            logger.debug("Empty message batch received")
            return JSONResponse({
                "status": "success",
                "received": 0,
                "written": 0,
                "sink_results": {}
            })
        
        # Log ingest details
        batch_info = {
            "messages": len(messages),
            "batch_size": payload.get("batch_size"),
            "timestamp": payload.get("timestamp"),
            "source": payload.get("source"),
            "is_retry": payload.get("is_retry", False)
        }
        logger.info("Data batch received", **batch_info)
        
        # Sanitize messages (remove internal fields)
        sanitized_messages = []
        for msg in messages:
            if isinstance(msg, dict):
                # Remove internal fields that start with underscore
                sanitized_msg = {k: v for k, v in msg.items() 
                               if not k.startswith('_')}
                if sanitized_msg:  # Only add non-empty messages
                    sanitized_messages.append(sanitized_msg)
        
        logger.debug("Messages sanitized", 
                    original=len(messages), 
                    sanitized=len(sanitized_messages))
        
        # Write to all enabled sinks
        sink_results = await sinks_manager.write_events(sanitized_messages)
        
        # Calculate totals
        total_written = sum(result.get("written", 0) for result in sink_results.values())
        total_errors = sum(result.get("errors", 0) for result in sink_results.values())
        
        # Return response with per-sink counts
        response_data = {
            "status": "success",
            "received": len(messages),
            "sanitized": len(sanitized_messages),
            "written": total_written,
            "errors": total_errors,
            "sink_results": sink_results
        }
        
        logger.info("Ingest completed", **response_data)
        return JSONResponse(response_data)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Ingest error", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )


@app.get("/health")
async def health_check() -> JSONResponse:
    """Health check endpoint including sink status."""
    try:
        health_status = sinks_manager.get_health_status()
        
        status_code = (
            status.HTTP_200_OK if health_status["healthy"] 
            else status.HTTP_503_SERVICE_UNAVAILABLE
        )
        
        response_data = {
            "status": "healthy" if health_status["healthy"] else "unhealthy",
            "timestamp": int(asyncio.get_event_loop().time()),
            **health_status
        }
        
        return JSONResponse(response_data, status_code=status_code)
        
    except Exception as e:
        logger.error("Health check error", error=str(e))
        return JSONResponse(
            {
                "status": "error",
                "error": str(e)
            },
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE
        )


@app.get("/")
async def root() -> JSONResponse:
    """Root endpoint with basic server information."""
    return JSONResponse({
        "service": "EdgeBot Mothership",
        "version": "1.0.0",
        "status": "running",
        "endpoints": {
            "ingest": "/ingest",
            "health": "/health"
        },
        "enabled_sinks": app_config.get_enabled_sinks() if app_config else []
    })


if __name__ == "__main__":
    import uvicorn
    import os
    
    # Configure logging
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
    
    config = get_config()
    uvicorn.run(
        "server:app",
        host=config.server.host,
        port=config.server.port,
        log_level=config.log_level.lower(),
        access_log=True
    )