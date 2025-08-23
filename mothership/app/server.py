"""FastAPI-based ingestion service for mothership with dual-sink support."""
import asyncio
import time
from datetime import datetime
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field, ValidationError
import structlog
from prometheus_client import CONTENT_TYPE_LATEST

from .config import ConfigManager
from .pipeline.processor import Pipeline
from .pipeline.processors_redaction import RedactionPipeline, PIISafetyValidator
from .pipeline.processors_enrich import (
    AddTagsProcessor, SeverityMapProcessor, ServiceFromPathProcessor,
    GeoHintProcessor, SiteEnvTagsProcessor, TimestampNormalizer
)
from .pipeline.llm_enricher import LLMEnricher
from .storage.tsdb import TimescaleDBWriter
# Import dual-sink components
from .storage.sinks import SinksManager  # NEW: dual-sink support
from .storage.loki import LokiClient  # NEW: Loki support
# Import new metrics module
from .metrics import (
    get_metrics_content,
    mship_ingest_batches_total,
    mship_ingest_events_total,
    mship_written_events_total,
    mship_sink_written_total,
    mship_ingest_seconds,
    mship_pipeline_seconds,
    mship_sink_write_seconds,
    mship_requests_total,
    mship_active_connections,
    mship_loki_queue_size
)

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
    """Ingest response with dual-sink support."""
    status: str
    processed_events: int
    processing_time: float
    sink_results: Dict[str, Dict[str, Any]]  # NEW: per-sink results
    errors: Optional[List[str]] = None

class HealthResponse(BaseModel):
    """Health check response with dual-sink status."""
    status: str
    timestamp: str
    version: str
    database: bool
    sinks: Dict[str, Dict[str, Any]]  # NEW: per-sink health
    enabled_sinks: List[str]  # NEW: list of enabled sinks
    pipeline_processors: List[str]

# Global state
app_state = {
    'config_manager': None,
    'pipeline': None,
    'tsdb_writer': None,
    'sinks_manager': None,  # NEW: dual-sink manager
    'startup_time': time.time()
}

# FastAPI app
app = FastAPI(
    title="Mothership Data Processor",
    description="Centralized data processing and ingestion service for AIOps EdgeBot with dual-sink support",
    version="1.5.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

@app.on_event("startup")
async def startup_event():
    """Initialize application on startup with dual-sink support."""
    try:
        logger.info("Starting Mothership service")
        
        # Load configuration
        config_manager = ConfigManager()
        config = config_manager.load_config()
        app_state['config_manager'] = config_manager
        
        # Configure logging level
        log_level = config.get('logging', {}).get('level', 'INFO')
        import logging
        logging.getLogger().setLevel(getattr(logging, log_level.upper(), logging.INFO))
        
        # Initialize TimescaleDB writer
        db_config = config['database']
        tsdb_writer = TimescaleDBWriter(db_config)
        await tsdb_writer.initialize()
        app_state['tsdb_writer'] = tsdb_writer
        
        # NEW: Initialize dual-sink manager
        sinks_manager = SinksManager(config)
        await sinks_manager.start()
        app_state['sinks_manager'] = sinks_manager
        
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
            service_processor = ServiceFromPathProcessor({})
            pipeline.add_processor(service_processor)
            
            # Geographic hints
            geo_processor = GeoHintProcessor({})
            pipeline.add_processor(geo_processor)
            
            # Site/environment tags
            site_processor = SiteEnvTagsProcessor({})
            pipeline.add_processor(site_processor)
            
            # Timestamp normalization
            timestamp_processor = TimestampNormalizer({})
            pipeline.add_processor(timestamp_processor)
        
        # 3. LLM enrichment (optional, with circuit breaker)
        if config.get('llm', {}).get('enabled', False):
            llm_processor = LLMEnricher(config['llm'])
            pipeline.add_processor(llm_processor)
        
        app_state['pipeline'] = pipeline
        
        logger.info("Mothership service started successfully", 
                   enabled_sinks=config_manager.get_enabled_sinks(),
                   pipeline_processors=[p.__class__.__name__ for p in pipeline.processors])
        
    except Exception as e:
        logger.error("Failed to start Mothership service", error=str(e))
        raise

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown."""
    logger.info("Shutting down Mothership service")
    
    # Stop dual-sink manager
    if app_state['sinks_manager']:
        await app_state['sinks_manager'].stop()
    
    # Close database connection
    if app_state['tsdb_writer']:
        await app_state['tsdb_writer'].close()
    
    logger.info("Mothership service shut down complete")

@app.post("/ingest", response_model=IngestResponse)
@mship_ingest_seconds.time()
async def ingest_events(request: IngestRequest) -> IngestResponse:
    """Ingest events for processing with dual-sink support."""
    start_time = time.time()
    
    try:
        events = request.messages
        if not events:
            mship_requests_total.labels(method='POST', endpoint='/ingest', status='400').inc()
            return IngestResponse(
                status="success",
                processed_events=0,
                processing_time=time.time() - start_time,
                sink_results={}
            )
        
        logger.info(f"Processing {len(events)} events")
        mship_ingest_batches_total.inc()
        mship_ingest_events_total.inc(len(events))
        
        # Process events through pipeline
        pipeline = app_state['pipeline']
        processed_events = []
        
        with mship_pipeline_seconds.time():
            for event in events:
                try:
                    # Convert to dict for pipeline processing
                    event_dict = event.dict()
                    processed_event = await pipeline.process_event(event_dict)
                    processed_events.append(processed_event)
                except Exception as e:
                    logger.error(f"Error processing event: {e}", event=event_dict)
                    continue
        
        # Store in dual-sink architecture
        sinks_manager = app_state['sinks_manager']
        sink_results = await sinks_manager.write_events(processed_events)
        
        # Update metrics as per requirements
        total_written = 0
        for sink_name, result in sink_results.items():
            written_count = result.get('written', 0)
            mship_sink_written_total.labels(sink=sink_name).inc(written_count)
            total_written += written_count
        
        mship_written_events_total.inc(total_written)
        
        # Update Loki queue size metric if Loki is enabled
        if 'loki' in sink_results:
            mship_loki_queue_size.set(sink_results['loki'].get('queued', 0))
        
        processing_time = time.time() - start_time
        mship_requests_total.labels(method='POST', endpoint='/ingest', status='200').inc()
        
        logger.info(f"Successfully processed {len(processed_events)} events", 
                   processing_time=processing_time,
                   sink_results=sink_results)
        
        return IngestResponse(
            status="success",
            processed_events=len(processed_events),
            processing_time=processing_time,
            sink_results=sink_results
        )
        
    except Exception as e:
        mship_requests_total.labels(method='POST', endpoint='/ingest', status='500').inc()
        logger.error("Error during ingestion", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/healthz", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Health check endpoint with dual-sink status."""
    try:
        # Check database connectivity
        tsdb_writer = app_state.get('tsdb_writer')
        database_healthy = tsdb_writer is not None and await tsdb_writer.health_check()
        
        # Check sink health
        sinks_manager = app_state['sinks_manager']
        sink_health = {}
        enabled_sinks = []
        
        if sinks_manager:
            # Check each sink
            for sink_name in sinks_manager.get_sink_names():
                sink = sinks_manager.get_sink(sink_name)
                if sink:
                    is_healthy = await sink.health_check()
                    sink_health[sink_name] = {
                        'healthy': is_healthy,
                        'enabled': sink.is_enabled()
                    }
                    if sink.is_enabled():
                        enabled_sinks.append(sink_name)
        
        # Get pipeline processors
        pipeline = app_state.get('pipeline')
        processors = [p.__class__.__name__ for p in pipeline.processors] if pipeline else []
        
        overall_status = "healthy" if database_healthy else "degraded"
        
        return HealthResponse(
            status=overall_status,
            timestamp=datetime.utcnow().isoformat() + "Z",
            version="1.5.0",
            database=database_healthy,
            sinks=sink_health,
            enabled_sinks=enabled_sinks,
            pipeline_processors=processors
        )
        
    except Exception as e:
        logger.error("Health check error", error=str(e))
        return HealthResponse(
            status="unhealthy",
            timestamp=datetime.utcnow().isoformat() + "Z",
            version="1.5.0",
            database=False,
            sinks={},
            enabled_sinks=[],
            pipeline_processors=[]
        )

@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint."""
    # Update active connections gauge
    if app_state.get('tsdb_writer'):
        mship_active_connections.set(app_state['tsdb_writer'].get_active_connections())
    
    return PlainTextResponse(get_metrics_content(), media_type=CONTENT_TYPE_LATEST)

@app.get("/stats")
async def get_stats() -> Dict[str, Any]:
    """Detailed service statistics with dual-sink info."""
    uptime = time.time() - app_state['startup_time']
    
    # Get pipeline stats
    pipeline = app_state.get('pipeline')
    pipeline_stats = {}
    if pipeline:
        for processor in pipeline.processors:
            processor_name = processor.__class__.__name__
            if hasattr(processor, 'get_stats'):
                pipeline_stats[processor_name] = processor.get_stats()
            else:
                pipeline_stats[processor_name] = {"processed": "N/A"}
    
    # Get sink stats
    sink_stats = {}
    sinks_manager = app_state.get('sinks_manager')
    if sinks_manager:
        for sink_name in sinks_manager.get_sink_names():
            sink = sinks_manager.get_sink(sink_name)
            if sink and hasattr(sink, 'get_stats'):
                sink_stats[sink_name] = sink.get_stats()
    
    return {
        "service": {
            "uptime": uptime,
            "version": "1.5.0"
        },
        "pipeline": {
            "processors": pipeline_stats
        },
        "sinks": sink_stats,
        "database": {
            "active_connections": app_state.get('tsdb_writer', {}).get_active_connections() if app_state.get('tsdb_writer') else 0
        }
    }

@app.get("/")
async def root():
    """Root endpoint with service information."""
    return {
        "service": "Mothership Data Processor",
        "version": "1.5.0",
        "description": "Centralized data processing and ingestion service with dual-sink support",
        "endpoints": {
            "ingest": "/ingest",
            "health": "/healthz",
            "metrics": "/metrics",
            "stats": "/stats",
            "docs": "/docs"
        }
    }

# Development server runner
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
    
    config_manager = ConfigManager()
    config = config_manager.load_config()
    
    server_config = config.get('server', {})
    uvicorn.run(
        "app.server:app",
        host=server_config.get('host', '0.0.0.0'),
        port=server_config.get('port', 8443),
        log_level=config.get('logging', {}).get('level', 'INFO').lower(),
        access_log=True,
        reload=os.getenv('DEV_MODE', 'false').lower() == 'true'
    )