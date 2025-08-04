from fastapi import APIRouter

from app.api.achievements import router as achievements_router
from app.api.auth import router as auth_router
from app.api.games import router as games_router
from app.api.logs import router as logs_router
from app.api.push import router as push_router
from app.api.web import router as web_router

router = APIRouter()
router.include_router(achievements_router)
router.include_router(auth_router)
router.include_router(games_router)
router.include_router(logs_router)
router.include_router(push_router)
router.include_router(web_router)
