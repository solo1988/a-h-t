from fastapi import APIRouter
from app.core.database import SessionLocal
from app.core.achievements import update_achievement
from app.models import AchievementData
from app.core.logger import logger_app

router = APIRouter()

# Обновление данных по достижению
@router.post("/api/update_achievement")
async def update_achievement_endpoint(data: AchievementData):
    async with SessionLocal() as session:
        logger_app.info("Отправили ачивку с удаленного вебсокета")
        await update_achievement(
            session=session,
            appid=data.appid,
            achievement_name=data.achievement_name,
            obtained_time=data.obtained_time,
            user_id=data.user_id
        )
        return {"message": "Achievement updated successfully"}
