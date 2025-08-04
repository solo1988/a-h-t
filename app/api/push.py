from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.future import select

from app.core.auth import manager
from app.core.database import SessionLocal
from app.models import Achievement, Game, PushSubscription, PushSubscriptionCreate, SubscriptionCheckRequest
from app.core.config import settings
from app.core.notifications import send_push_notification_async
from app.core.telegram import send_telegram_message_with_image
from app.core.logger import logger_app

router = APIRouter()

# Отправка тестового уведомления
@router.get("/send_test_notification")
async def send_test_notification():
    achiev_name = "softUnderbelly"

    async with SessionLocal() as db:
        result = await db.execute(
            select(Achievement).where(Achievement.name == achiev_name).where(Achievement.user_id == 1))
        achievement = result.scalars().first()

        if achievement is None:
            return {"error": "Достижение не найдено"}

        appid = achievement.appid
        result = await db.execute(select(Game).filter(Game.appid == appid).filter(Game.user_id == 1))
        game = result.scalars().first()

        if game is None:
            return {"error": "Игра не найдена"}

        title = achievement.displayname
        body = f"Вы получили достижение: {title}"
        icon = achievement.icon
        url = achievement.icongray
        message = f"Ачивка в игре {game.name}: {title}\nСсылка: {url}"

        subscriptions_result = await db.execute(select(PushSubscription))
        subscriptions = subscriptions_result.scalars().all()

        for sub in subscriptions:
            await send_push_notification_async(sub, title, body, icon, url)
        logger_app.info(f"Пуши отправлены на {len(subscriptions)} подписок: {title}")

        for user_id, telegram_id in settings.USER_TO_TELEGRAM.items():
            send_telegram_message_with_image(telegram_id, message, settings.BOT_TOKEN, icon)

    return {"message": "Тестовое уведомление отправлено"}

# Проверка подписки
@router.post("/check_subscription")
async def check_subscription(data: SubscriptionCheckRequest, user=Depends(manager)):
    async with SessionLocal() as db:
        result = await db.execute(select(PushSubscription).where(
            PushSubscription.endpoint == data.endpoint,
            PushSubscription.user_id == user.id
        ))
        sub = result.scalar_one_or_none()
        return {"exists": sub is not None}

# Подписка
@router.post("/subscribe")
async def subscribe(subscription: PushSubscriptionCreate, user=Depends(manager)):
    async with SessionLocal() as db:
        new_sub = PushSubscription(
            endpoint=subscription.endpoint,
            p256dh=subscription.p256dh,
            auth=subscription.auth,
            user_id=user.id
        )
        db.add(new_sub)
        try:
            await db.commit()
            return {"message": "Подписка сохранена"}
        except Exception as e:
            await db.rollback()
            raise HTTPException(status_code=500, detail=f"Ошибка: {e}")
