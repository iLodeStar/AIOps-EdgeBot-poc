"""FastAPI-based ingestion service for mothership."""
import asyncio
import time
from datetime import datetime
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field, ValidationError
import structlog
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST

from .config import ConfigManager
from .pipeline.processor import Pipeline
from .pipeline.processors_redaction import RedactionPipeline, PIISafetyValidator
from .pipeline.processors_enrich import (
    AddTagsProcessor, SeverityMapProcessor, ServiceFromPathProcessor,
    GeoHintProcessor, SiteEnvTagsProcessor, TimestampNormalizer
)
from .pipeline.llm_enricher import LLMEnricher
from .storage.tsdb import TimescaleDBWriter

# Configure logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()

# Prometheus metrics
INGESTION_REQUESTS = Counter('mothership_ingestion_requests_total', 'Total ingestion requests', ['status'])
INGESTION_EVENTS = Counter('mothership_ingestion_events_total', 'Total events processed')
INGESTION_DURATION = Histogram('mothership_ingestion_duration_seconds', 'Request processing duration')
PIPELINE_DURATION = Histogram('mothership_pipeline_duration_seconds', 'Pipeline processing duration')
DATABASE_WRITES = Counter('mothership_database_writes_total', 'Total database writes', ['status'])
ACTIVE_CONNECTIONS = Gauge('mothership_active_connections', 'Active database connections')

# Pydantic models
class Event(BaseModel):
    """Individual event model."""
    timestamp: Optional[str] = None
    type: str = Field(..., description="Event type (syslog, log, snmp, flow, nmea, weather)")
    source: Optional[str] = None
    message: Optional[str] = None
    data: Optional[Dict[str, Any]] = None

    class Config:
        extra = "allow"  # Allow additional fields

class IngestRequest(BaseModel):
    """Ingest request containing array of events."""
    messages: List[Event] = Field(..., description="Array of events to ingest")
    batch_metadata: Optional[Dict[str, Any]] = None

class IngestResponse(BaseModel):
    """Ingest response."""
    status: str
    processed_events: int
    processing_time: float
    errors: Optional[List[str]] = None

class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    timestamp: str
    version: str
    database: bool
    pipeline_processors: List[str]

# Global state
app_state = {
    'config_manager': None,
    'pipeline': None,
    'tsdb_writer': None,
    'startup_time': time.time()
}

# FastAPI app
app = FastAPI(
    title="Mothership Data Processor",
    description="Centralized data processing and ingestion service for AIOps EdgeBot",
    version="1.5.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

@app.on_event("startup")
async def startup_event():
    """Initialize application on startup."""
    try:
        logger.info("Starting Mothership service")
        
        # Load configuration
        config_manager = ConfigManager()
        config = config_manager.load_config()
        app_state['config_manager'] = config_manager
        
        # Configure logging level
        log_level = config.get('logging', {}).get('level', 'INFO')
        structlog.configure(
            wrapper_class=structlog.make_filtering_bound_logger(
                getattr(structlog.stdlib.LoggingLogLevel, log_level)
            )
        )
        
        # Initialize TimescaleDB writer
        db_config = config['database']
        tsdb_writer = TimescaleDBWriter(db_config)
        await tsdb_writer.initialize()
        app_state['tsdb_writer'] = tsdb_writer
        
        # Initialize processing pipeline
        pipeline = Pipeline(config['pipeline'])
        
        # Add processors in order (redaction FIRST for PII safety)
        processor_config = config['pipeline']['processors']
        
        # 1. Redaction pipeline (MUST be first)
        if processor_config.get('redaction', {}).get('enabled', True):
            redaction_processor = RedactionPipeline(processor_config)
            pipeline.add_processor(redaction_processor)
            
            # Add PII safety validator
            pii_validator = PIISafetyValidator({'strict_mode': False})
            pipeline.add_processor(pii_validator)
        
        # 2. Deterministic enrichment
        if processor_config.get('enrichment', {}).get('enabled', True):
            enrich_config = processor_config['enrichment']
            
            # Add tags
            if enrich_config.get('add_tags'):
                add_tags_processor = AddTagsProcessor(enrich_config)
                pipeline.add_processor(add_tags_processor)
            
            # Severity mapping
            severity_processor = SeverityMapProcessor(enrich_config)
            pipeline.add_processor(severity_processor)
            
            # Service extraction
            service_processor = ServiceFromPathProcessor(enrich_config)
            pipeline.add_processor(service_processor)
            
            # Geo hints (if configured)
            if enrich_config.get('geo_hints'):
                geo_processor = GeoHintProcessor(enrich_config['geo_hints'])
                pipeline.add_processor(geo_processor)
            
            # Site/environment tags
            if enrich_config.get('site_env_tags'):
                site_env_processor = SiteEnvTagsProcessor(enrich_config['site_env_tags'])
                pipeline.add_processor(site_env_processor)
            
            # Timestamp normalization
            timestamp_processor = TimestampNormalizer(enrich_config)
            pipeline.add_processor(timestamp_processor)
        
        # 3. LLM enrichment (AFTER redaction and deterministic enrichment)
        llm_config = config.get('llm', {})
        if llm_config.get('enabled', False):
            llm_processor = LLMEnricher(llm_config)
            pipeline.add_processor(llm_processor)
            logger.info("LLM enrichment enabled")
        else:
            logger.info("LLM enrichment disabled")
        
        app_state['pipeline'] = pipeline
        
        logger.info("Mothership service started successfully",
                   processors=pipeline.get_enabled_processors())
        
    except Exception as e:
        logger.error("Failed to start Mothership service", error=str(e))
        raise

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown."""
    logger.info("Shutting down Mothership service")
    
    if app_state['tsdb_writer']:
        await app_state['tsdb_writer'].close()
    
    # Cleanup LLM resources if any
    if app_state['pipeline']:
        for processor in app_state['pipeline'].processors:
            if hasattr(processor, 'cleanup'):
                await processor.cleanup()
    
    logger.info("Mothership service shutdown complete")

def get_dependencies():
    """Get application dependencies."""
    return {
        'config': app_state['config_manager'].get_config() if app_state['config_manager'] else {},
        'pipeline': app_state['pipeline'],
        'tsdb_writer': app_state['tsdb_writer']
    }

@app.post("/ingest", response_model=IngestResponse)
async def ingest_events(
    request: IngestRequest,
    http_request: Request,
    deps: Dict = Depends(get_dependencies)
) -> IngestResponse:
    """
    Ingest a batch of events for processing.
    
    - Validates event schema
    - Runs through processing pipeline (redaction -> enrichment -> LLM)
    - Writes to TimescaleDB
    """
    start_time = time.time()
    pipeline = deps['pipeline']
    tsdb_writer = deps['tsdb_writer']
    errors = []
    
    try:
        with INGESTION_DURATION.time():
            logger.info("Received ingest request",
                       event_count=len(request.messages),
                       client=http_request.client.host if http_request.client else None)
            
            # Convert Pydantic models to dicts
            events = [event.dict() for event in request.messages]
            
            # Process through pipeline
            with PIPELINE_DURATION.time():
                processed_events = await pipeline.process_events(events)
            
            # Write to database
            if processed_events:
                success = await tsdb_writer.insert_events(processed_events)
                if success:
                    DATABASE_WRITES.labels(status='success').inc()
                    INGESTION_EVENTS.inc(len(processed_events))
                else:
                    DATABASE_WRITES.labels(status='error').inc()
                    errors.append("Database write failed")
            
            processing_time = time.time() - start_time
            
            INGESTION_REQUESTS.labels(status='success').inc()
            
            logger.info("Ingest request completed successfully",
                       processed_events=len(processed_events),
                       processing_time=processing_time)
            
            return IngestResponse(
                status="success",
                processed_events=len(processed_events),
                processing_time=processing_time,
                errors=errors if errors else None
            )
            
    except ValidationError as e:
        INGESTION_REQUESTS.labels(status='validation_error').inc()
        logger.warning("Validation error in ingest request", error=str(e))
        raise HTTPException(status_code=400, detail=f"Validation error: {str(e)}")
        
    except Exception as e:
        INGESTION_REQUESTS.labels(status='error').inc()
        logger.error("Error processing ingest request", error=str(e))
        raise HTTPException(status_code=500, detail=f"Processing error: {str(e)}")

@app.get("/healthz", response_model=HealthResponse)
async def health_check(deps: Dict = Depends(get_dependencies)) -> HealthResponse:
    """
    Health check endpoint.
    
    Returns service health status including database connectivity.
    """
    try:
        tsdb_writer = deps['tsdb_writer']
        pipeline = deps['pipeline']
        
        # Check database health
        db_healthy = await tsdb_writer.health_check() if tsdb_writer else False
        
        # Get pipeline processors
        processors = pipeline.get_enabled_processors() if pipeline else []
        
        status = "healthy" if db_healthy else "degraded"
        
        return HealthResponse(
            status=status,
            timestamp=datetime.utcnow().isoformat(),
            version="1.5.0",
            database=db_healthy,
            pipeline_processors=processors
        )
        
    except Exception as e:
        logger.error("Health check failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"Health check failed: {str(e)}")

@app.get("/metrics")
async def metrics():
    """
    Prometheus metrics endpoint.
    
    Returns metrics in Prometheus format.
    """
    try:
        # Update active connections gauge
        if app_state['tsdb_writer'] and app_state['tsdb_writer'].pool:
            pool_stats = app_state['tsdb_writer'].pool.get_stats()
            ACTIVE_CONNECTIONS.set(pool_stats.pool_size - pool_stats.pool_available)
        
        return PlainTextResponse(
            generate_latest(),
            media_type=CONTENT_TYPE_LATEST
        )
    except Exception as e:
        logger.error("Failed to generate metrics", error=str(e))
        raise HTTPException(status_code=500, detail="Metrics generation failed")

@app.get("/stats")
async def get_stats(deps: Dict = Depends(get_dependencies)) -> Dict[str, Any]:
    """
    Get detailed service statistics.
    
    Returns pipeline and database statistics.
    """
    try:
        stats = {
            'service': {
                'uptime': time.time() - app_state['startup_time'],
                'version': '1.5.0',
                'startup_time': app_state['startup_time']
            }
        }
        
        # Pipeline stats
        if deps['pipeline']:
            stats['pipeline'] = deps['pipeline'].get_stats()
        
        # Database stats
        if deps['tsdb_writer']:
            stats['database'] = await deps['tsdb_writer'].get_stats()
        
        return stats
        
    except Exception as e:
        logger.error("Failed to get stats", error=str(e))
        raise HTTPException(status_code=500, detail=f"Stats generation failed: {str(e)}")

@app.get("/")
async def root():
    """Root endpoint with service info."""
    return {
        "service": "Mothership Data Processor",
        "version": "1.5.0",
        "description": "Centralized data processing and ingestion service",
        "endpoints": {
            "ingest": "POST /ingest - Ingest events for processing",
            "health": "GET /healthz - Health check",
            "metrics": "GET /metrics - Prometheus metrics",
            "stats": "GET /stats - Detailed statistics",
            "docs": "GET /docs - API documentation"
        }
    }

# Error handlers
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Custom HTTP exception handler with logging."""
    logger.warning("HTTP exception", 
                  status_code=exc.status_code, 
                  detail=exc.detail,
                  path=request.url.path)
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail, "status_code": exc.status_code}
    )

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """General exception handler."""
    logger.error("Unhandled exception", 
                error=str(exc), 
                path=request.url.path)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "status_code": 500}
    )

# Development server entry point
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "mothership.app.server:app",
        host="0.0.0.0",
        port=8443,
        log_level="info",
        reload=True
    )