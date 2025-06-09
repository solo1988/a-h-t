import datetime
import logging
import os
from typing import Optional

import dateparser
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from pytz import timezone

from database import SessionLocal
from models import Favorite, Release

from dotenv import load_dotenv
import httpx

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
TELEGRAM_IDS = os.getenv("TELEGRAM_IDS", "")
ALLOWED_USER_IDS = {int(uid) for uid in TELEGRAM_IDS.split(",") if uid.strip().isdigit()}

user_to_telegram_id = {
    1: 558950992,
    2: 731299888,
}


async def send_telegram_message_with_image_async(chat_id: int, message: str, bot_token: str, image_url: str):
    url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
    payload = {
        "chat_id": chat_id,
        "caption": message,
        "parse_mode": "HTML",
        "photo": image_url
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(url, data=payload)
        return response


def parse_release_date(date_str: str) -> Optional[datetime.date]:
    if not date_str:
        return None

    #logging.info(f"[check_favorites] Исходная строка для dateparser: '{date_str}'")

    parsed = dateparser.parse(
        date_str,
        settings={"PREFER_DAY_OF_MONTH": "first"}
    )

    if parsed:
        parsed_date = parsed.date()
        #logging.info(f"[check_favorites] Успешно распарсено '{date_str}' как {parsed_date}")
        return parsed_date
    else:
        #logging.warning(f"[check_favorites] Не удалось распарсить дату: '{date_str}'")
        return None


async def check_daily_releases():
    #today = datetime.date.today() + datetime.timedelta(days=2)
    today = datetime.date.today()
    #logging.info(f"[check_favorites] Проверка релизов на {today}")

    async with SessionLocal() as session:
        stmt = (
            select(Favorite)
            .options(selectinload(Favorite.release))
            .join(Release, Favorite.appid == Release.appid)
        )
        result = await session.execute(stmt)
        favorites = result.scalars().all()

        #logging.info(f"[check_favorites] Найдено избранных: {len(favorites)}")

        releases_by_user = {}

        for fav in favorites:
            release = fav.release
            parsed_date = parse_release_date(release.release_date)
            if parsed_date == today:
                releases_by_user.setdefault(fav.user_id, []).append(release)

        if not releases_by_user:
            #logging.info("[check_favorites] Сегодня нет релизов в избранных играх.")
            return

        #logging.info(f"[check_favorites] Сегодня выходят избранные игры: {releases_by_user}")

        for user_id, releases in releases_by_user.items():
            telegram_id = user_to_telegram_id.get(user_id)
            if telegram_id is None or telegram_id not in ALLOWED_USER_IDS:
                #logging.warning(f"[check_favorites] Пользователь {user_id} не в списке разрешённых.")
                continue

            message_lines = [f"🎮 <b>Сегодня выходят игры из вашего избранного:</b>\n"]
            for rel in releases:
                message_lines.append(f"• {rel.name} — дата релиза: {rel.release_date}")

            message = "\n".join(message_lines)

            image_url = f"https://cdn.cloudflare.steamstatic.com/steam/apps/{releases[0].appid}/header.jpg"

            try:
                response = await send_telegram_message_with_image_async(telegram_id, message, BOT_TOKEN, image_url)
            except Exception as e:
                #logging.error(f"[check_favorites] Исключение при отправке сообщения пользователю {telegram_id}: {e}")
                print(f"[check_favorites] Исключение при отправке сообщения пользователю {telegram_id}: {e}")


def start_scheduler():
    scheduler = AsyncIOScheduler()
    #logging.info("[check_favorites] Планировщик запущен")
    scheduler.add_job(
        check_daily_releases,
        CronTrigger(hour=14, minute=58, timezone=timezone("Europe/Moscow"))
    )
    scheduler.start()
    return scheduler
