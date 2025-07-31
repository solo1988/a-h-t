import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import datetime
import logging
import json
import os
from typing import Optional
import urllib.parse

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

logger = logging.getLogger("releases")
logger.setLevel(logging.INFO)
logger.propagate = False

file_handler = logging.FileHandler("releases.log", encoding="utf-8")
formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

BOT_TOKEN = os.getenv("BOT_TOKEN")
TELEGRAM_IDS = os.getenv("TELEGRAM_IDS", "")
ALLOWED_USER_IDS = {int(uid) for uid in TELEGRAM_IDS.split(",") if uid.strip().isdigit()}

user_to_telegram_id = {
    1: 558950992,
    2: 731299888,
}

async def send_telegram_message_with_image_async(chat_id: int, message: str, bot_token: str, image_url: str, buttons: list[dict]):
    url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"

    # Добавляем хэштег, если его нет
    if "#релиз" not in message:
        message += "\n\n#релиз"

    reply_markup = {
        "inline_keyboard": [buttons]
    }

    payload = {
        "chat_id": chat_id,
        "caption": message,
        "parse_mode": "HTML",
        "photo": image_url,
        "reply_markup": json.dumps(reply_markup)
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(url, data=payload)
        response_data = response.json()

        if not response_data.get("ok"):
            print(f"[send_telegram_message] Ошибка отправки сообщения: {response_data}")
            return response

        # Получаем message_id отправленного сообщения
        message_id = response_data["result"]["message_id"]

        # Пытаемся закрепить сообщение
        pin_url = f"https://api.telegram.org/bot{bot_token}/pinChatMessage"
        pin_payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "disable_notification": True  # без уведомления
        }

        try:
            pin_response = await client.post(pin_url, data=pin_payload)
            pin_data = pin_response.json()
            if not pin_data.get("ok"):
                print(f"[pinChatMessage] Не удалось закрепить сообщение: {pin_data}")
        except Exception as e:
            print(f"[pinChatMessage] Исключение при попытке закрепить сообщение: {e}")

        return response

def parse_release_date(date_str: str) -> Optional[datetime.date]:
    if not date_str:
        return None

    parsed = dateparser.parse(
        date_str,
        settings={"PREFER_DAY_OF_MONTH": "first"}
    )

    if parsed:
        parsed_date = parsed.date()
        return parsed_date
    else:
        return None


async def check_daily_releases():
    today = datetime.date.today()
    logger.info(f"[check_favorites] Проверка релизов на {today}")

    async with SessionLocal() as session:
        stmt = (
            select(Favorite)
            .options(selectinload(Favorite.release))
            .join(Release, Favorite.appid == Release.appid)
        )
        result = await session.execute(stmt)
        favorites = result.scalars().all()

        logger.info(f"[check_favorites] Найдено избранных: {len(favorites)}")

        releases_by_user = {}

        for fav in favorites:
            release = fav.release
            parsed_date = parse_release_date(release.release_date)
            if parsed_date == today:
                releases_by_user.setdefault(fav.user_id, []).append(release)

        if not releases_by_user:
            logger.info("[check_favorites] Сегодня нет релизов в избранных играх.")
            return

        logger.info(f"[check_favorites] Сегодня выходят избранные игры: {releases_by_user}")

        for user_id, releases in releases_by_user.items():
            telegram_id = user_to_telegram_id.get(user_id)
            if telegram_id is None or telegram_id not in ALLOWED_USER_IDS:
                continue

            for rel in releases:
                message_lines = [f"🎮 <b>Сегодня выходят игры из вашего избранного:</b>\n"]
                message_lines.append(f"• {rel.name} — дата релиза: {rel.release_date}\n\n")
                message_lines.append("#релиз")
                message = "\n".join(message_lines)

                image_url = f"https://cdn.cloudflare.steamstatic.com/steam/apps/{rel.appid}/header.jpg"
                query = urllib.parse.quote(rel.name)

                buttons = [
                    {"text": "Rutor", "url": f"https://rutor.info/search/0/8/000/0/{query}"},
                    {"text": "RuTracker", "url": f"https://rutracker.org/forum/tracker.php?f=...&nm={query}"}
                ]

                try:
                    response = await send_telegram_message_with_image_async(
                        telegram_id, message, BOT_TOKEN, image_url, buttons
                    )
                except Exception as e:
                    print(f"[check_favorites] Исключение при отправке сообщения пользователю {telegram_id}: {e}")


def start_scheduler():
    scheduler = AsyncIOScheduler()
    logger.info("[check_favorites] Планировщик запущен")
    scheduler.add_job(
        check_daily_releases,
        CronTrigger(hour=11, minute=0, timezone=timezone("Europe/Moscow")),
        misfire_grace_time=300  # в секундах
    )
    scheduler.start()
    return scheduler

if __name__ == "__main__":
    import asyncio
    asyncio.run(check_daily_releases())