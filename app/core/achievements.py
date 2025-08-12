from datetime import datetime
from app.core.database import SessionLocal
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Achievement, PushSubscription, Game
from sqlalchemy.future import select

from app.core.notifications import send_push_notification_async
from app.core.config import settings
from app.core.telegram import send_telegram_message_with_image
from app.core.logger import logger_app


# Получение всех достижений для игры по appid
async def get_achievements_for_game(db: AsyncSession, appid: int, id: int):
    result = await db.execute(select(Achievement).filter(Achievement.appid == appid).filter(Achievement.user_id == id))
    achievements = result.scalars().all()
    return achievements


# Получение общего количества достижений для игры
async def get_total_achievements_for_game(db: AsyncSession, appid: int, id: int):
    try:
        result = await db.execute(
            select(Achievement).filter(Achievement.appid == appid).filter(Achievement.user_id == id))
        achievements = result.scalars().all()
        return len(achievements)
    except Exception as e:
        raise e


# Получение количества полученных достижений для игры
async def get_earned_achievements_for_game(db: AsyncSession, appid: int, id: int):
    try:
        result = await db.execute(
            select(func.count(Achievement.id))
            .filter(Achievement.appid == appid).filter(Achievement.user_id == id)
            .filter(Achievement.obtained_date != None)  # Фильтрация по полученным достижениям
        )
        earned_achievements = result.scalar_one()  # Получаем количество
        return earned_achievements
    except Exception as e:
        raise e


# Получение самой свежей ачивки
async def get_last_obtained_date_for_game(db: AsyncSession, appid: int, id: int):
    result = await db.execute(
        select(func.max(Achievement.obtained_date))
        .where(Achievement.appid == appid).where(Achievement.user_id == id)
        .where(Achievement.obtained_date != "0")
    )
    return result.scalar_one_or_none()


# Обновление ачивки
async def update_achievement(session: AsyncSession, appid: int, achievement_name: str, obtained_time: int,
                             user_id: int, ):
    obtained_date = datetime.utcfromtimestamp(obtained_time)

    query = select(Achievement).where(Achievement.appid == appid, Achievement.name == achievement_name,
                                      Achievement.user_id == user_id)
    result = await session.execute(query)
    achievement = result.scalar_one_or_none()

    if achievement:
        achievement.obtained_date = obtained_date
        await session.commit()
        logger_app.info(f"Обновлено достижение {achievement.displayname}")

        title = achievement.displayname
        body = f"Вы получили достижение: {achievement_name}!"
        icon = achievement.icon
        url = achievement.icongray

        async with SessionLocal() as db:
            subscriptions_result = await db.execute(select(PushSubscription).where(PushSubscription.user_id == user_id))
            subscriptions = subscriptions_result.scalars().all()

            for sub in subscriptions:
                await send_push_notification_async(sub, title, body, icon, url)
            logger_app.info(f"Пуши отправлены на {len(subscriptions)} подписок: {title}")

        result = await session.execute(select(Game).filter(Game.appid == appid).filter(Game.user_id == user_id))
        game = result.scalars().first()

        if game is None:
            logger_app.error("Игра не найдена")
            return {"error": "Игра не найдена"}

        game_name = game.name
        message = f"Ачивка в игре {game_name}: {title}\nСсылка: {url}"

        for tg_user_id, telegram_id in settings.USER_TO_TELEGRAM.items():
            if user_id == tg_user_id:
                send_telegram_message_with_image(telegram_id, message, settings.BOT_TOKEN, icon)
                logger_app.info(f"Отправили уведомление в телеграм {title}")
                logger_app.info("-" * 60)


# Формирование ссылок для ачивки
async def get_achievement_url(game_name: str, displayname: str):
    game_name_slug = game_name.lower().replace("&amp;", "").replace("&", "_").replace(" ", "_").replace(":", "")
    game_name_slug = game_name_slug.replace("__", "_")

    achievement_slug = displayname.lower().replace(" ", "_").replace("!", "_voskl").replace("’", "").replace("'", "")
    achievement_slug = achievement_slug.replace("__", "_")

    url = f"https://stratege.ru/ps5/trophies/{game_name_slug}/spisok/{achievement_slug}"
    return url
