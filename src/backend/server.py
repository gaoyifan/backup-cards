from fastapi import FastAPI
from strawberry.fastapi import GraphQLRouter
from backend.schema import schema, backup_manager, add_log
from backend.monitor import DeviceMonitor
from contextlib import asynccontextmanager
import logging

# Configure logging
# logging.basicConfig(level=logging.INFO) # Handled by main.py
logger = logging.getLogger(__name__)

monitor = None

async def device_callback(device):
    logger.info(f"Device detected: {device.device_node}")
    add_log(f"Device detected: {device.device_node}")
    
    try:
        mount_point = await backup_manager.mount_device(device)
        add_log(f"Mounted at {mount_point}")
        
        target_path = await backup_manager.resolve_target_path(device, mount_point)
        add_log(f"Target path resolved: {target_path}")
        
        add_log(f"Starting automatic backup to {target_path}")
        await backup_manager.perform_backup(mount_point, target_path)
        add_log("Automatic backup completed")
        
    except Exception as e:
        logger.error(f"Automatic backup failed: {e}")
        add_log(f"Automatic backup failed: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    global monitor
    monitor = DeviceMonitor(callback=device_callback)
    await monitor.start()
    try:
        yield
    finally:
        if monitor:
            await monitor.stop()

app = FastAPI(lifespan=lifespan)

graphql_app = GraphQLRouter(schema)
app.include_router(graphql_app, prefix="/graphql")

@app.get("/")
async def root():
    return {"message": "SD Backup Backend Running"}
