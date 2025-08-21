#!/usr/bin/env python3
"""Quick test script to verify EdgeBot can start and stop."""
import asyncio
import sys
from pathlib import Path
import signal
import time

# Add the app directory to the path
sys.path.insert(0, str(Path(__file__).parent / 'app'))

from app.main import EdgeBotSupervisor


async def test_startup():
    """Test EdgeBot startup and shutdown."""
    config_path = str(Path(__file__).parent / 'config.yaml')
    
    print("Creating EdgeBot supervisor...")
    supervisor = EdgeBotSupervisor(config_path)
    
    print("Starting EdgeBot...")
    task = asyncio.create_task(supervisor.start())
    
    # Let it run for a few seconds
    await asyncio.sleep(3)
    
    print("Triggering shutdown...")
    supervisor.shutdown_event.set()
    
    try:
        await asyncio.wait_for(task, timeout=10)
        print("✅ EdgeBot started and stopped successfully!")
        return True
    except asyncio.TimeoutError:
        print("❌ EdgeBot failed to shutdown within timeout")
        task.cancel()
        return False
    except Exception as e:
        print(f"❌ EdgeBot failed with error: {e}")
        return False


if __name__ == '__main__':
    success = asyncio.run(test_startup())
    sys.exit(0 if success else 1)