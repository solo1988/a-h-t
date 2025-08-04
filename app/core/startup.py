from app.core.database import init_db
from app.core.scheduler import start_scheduler
from app.core.listeners import websocket_listener
import asyncio

def register_startup(app):
    @app.on_event("startup")
    async def startup():
        await init_db()
        start_scheduler()
        asyncio.create_task(websocket_listener())