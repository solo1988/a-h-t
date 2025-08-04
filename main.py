import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app.api.router import router
from app.core.config import settings
from app.core.startup import register_startup
from app.core.middleware import register_middleware
from app.core.auth import manager

app = FastAPI()

# Мидлварь и сессии
app.add_middleware(SessionMiddleware, settings.SECRET_KEY)

# Статика и шаблоны
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/.well-known", StaticFiles(directory="./.well-known"), name=".well-known")

# Подключение логики
register_startup(app)
register_middleware(app, manager)

# Роуты
app.include_router(router)

# Для локального запуска
if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)