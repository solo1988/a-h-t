import websockets
import json
import asyncio
import logging
from app.core.database import SessionLocal

from app.core.achievements import update_achievement

async def websocket_listener():
    uri = "ws://192.168.1.111:8082"
    user_id = 1
    while True:
        try:
            async with websockets.connect(uri) as websocket:
                async for message in websocket:
                    data = json.loads(message)
                    async with SessionLocal() as session:
                        obtained_time = int(data["time"]) + 3 * 3600

                        asyncio.create_task(
                            update_achievement(session, int(data["appID"]), data["achievement"], obtained_time,
                                               user_id))
                        logging.info("Отправили ачивку с локального вебсокета")
        except Exception as e:
            await asyncio.sleep(5)