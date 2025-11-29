import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from strawberry.fastapi import GraphQLRouter

from backend.monitor import DeviceMonitor, monitoring_supported
from backend.schema import backup_manager, schema

logger = logging.getLogger(__name__)

monitor: DeviceMonitor | None = None


async def device_callback(device):
    logger.info("Device detected: %s", device.device_node)
    try:
        await backup_manager.handle_device(device)
    except Exception as exc:
        logger.exception("Automatic backup failed: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global monitor
    # Mark stale tasks as failed from previous run
    await backup_manager.fail_stale_tasks()
    
    if monitoring_supported():
        monitor = DeviceMonitor(callback=device_callback)
        await monitor.start()
    else:
        logger.info("Skipping device monitoring (unsupported platform or pyudev missing).")
    try:
        yield
    except asyncio.CancelledError:
        logger.info("Lifespan cancelled; shutting down gracefully.")
    finally:
        if monitor:
            await monitor.stop()


app = FastAPI(lifespan=lifespan)
graphql_app = GraphQLRouter(schema)
app.include_router(graphql_app, prefix="/graphql")


@app.get("/")
async def root():
    return {"message": "SD Backup Backend Running"}
