from fastapi import APIRouter, Path
from fastapi.responses import PlainTextResponse
import os

router = APIRouter()

# Возврат содержимого логов
@router.get("/log/{log_name}", response_class=PlainTextResponse)
async def get_log(log_name: str = Path(..., pattern="^(app|releases|updater)$")):
    filename = f"{log_name}.log"
    log_path = os.path.join(os.getcwd(), filename)
    if os.path.exists(log_path):
        with open(log_path, "r", encoding="utf-8") as f:
            return f.read()
    return f"Файл {filename} не найден."