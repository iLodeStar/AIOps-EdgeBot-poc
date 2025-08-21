import asyncio
import logging
import os
from typing import Optional

import requests
from fastapi import FastAPI
from pydantic import BaseModel
from dotenv import load_dotenv

from .sim import create_telemetry_data

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
EDGE_ID = os.getenv("EDGE_ID", "edge-1")
CENTRAL_API_BASE = os.getenv("CENTRAL_API_BASE", "http://central:8000")
SEND_INTERVAL_SEC = int(os.getenv("SEND_INTERVAL_SEC", "5"))

app = FastAPI(
    title="AIOps EdgeBot Edge Node",
    description=f"Edge node {EDGE_ID} for telemetry collection and transmission",
    version="1.0.0"
)


class HealthResponse(BaseModel):
    status: str
    edge_id: str
    central_api_base: str
    send_interval_sec: int


class EdgeNodeConfig:
    """Edge node configuration and state"""
    def __init__(self):
        self.edge_id = EDGE_ID
        self.central_api_base = CENTRAL_API_BASE
        self.send_interval_sec = SEND_INTERVAL_SEC
        self.running = False
        self.telemetry_task: Optional[asyncio.Task] = None


config = EdgeNodeConfig()


async def send_telemetry():
    """Send telemetry data to central platform"""
    try:
        telemetry_data = create_telemetry_data(config.edge_id)
        
        response = requests.post(
            f"{config.central_api_base}/ingest",
            json=telemetry_data,
            timeout=10
        )
        
        if response.status_code == 200:
            logger.info(f"Telemetry sent successfully: {telemetry_data['ts']}")
        else:
            logger.warning(f"Failed to send telemetry: {response.status_code} {response.text}")
            
    except requests.exceptions.RequestException as e:
        logger.error(f"Error sending telemetry: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error sending telemetry: {str(e)}")


async def telemetry_loop():
    """Background task to continuously send telemetry"""
    logger.info(f"Starting telemetry loop for {config.edge_id}, interval: {config.send_interval_sec}s")
    
    while config.running:
        await send_telemetry()
        await asyncio.sleep(config.send_interval_sec)
    
    logger.info("Telemetry loop stopped")


@app.on_event("startup")
async def startup_event():
    """Start the telemetry background task"""
    logger.info(f"Starting Edge Node {config.edge_id}")
    logger.info(f"Central API: {config.central_api_base}")
    logger.info(f"Send interval: {config.send_interval_sec} seconds")
    
    config.running = True
    config.telemetry_task = asyncio.create_task(telemetry_loop())


@app.on_event("shutdown")
async def shutdown_event():
    """Stop the telemetry background task"""
    logger.info(f"Shutting down Edge Node {config.edge_id}")
    
    config.running = False
    if config.telemetry_task:
        config.telemetry_task.cancel()
        try:
            await config.telemetry_task
        except asyncio.CancelledError:
            pass


@app.get("/healthz", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    return HealthResponse(
        status="ok",
        edge_id=config.edge_id,
        central_api_base=config.central_api_base,
        send_interval_sec=config.send_interval_sec
    )


@app.get("/config")
async def get_config():
    """Get current configuration"""
    return {
        "edge_id": config.edge_id,
        "central_api_base": config.central_api_base,
        "send_interval_sec": config.send_interval_sec,
        "running": config.running
    }


if __name__ == "__main__":
    import uvicorn
    
    # For standalone mode, run without FastAPI (just the telemetry sender)
    if os.getenv("STANDALONE_MODE", "false").lower() == "true":
        async def standalone_main():
            config.running = True
            await telemetry_loop()
        
        try:
            asyncio.run(standalone_main())
        except KeyboardInterrupt:
            logger.info("Standalone edge node stopped")
    else:
        # Run with FastAPI server
        uvicorn.run(app, host="0.0.0.0", port=8001)