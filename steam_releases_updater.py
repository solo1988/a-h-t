from sqlalchemy.orm import Session
from models import Release, Favorite
from database import SyncSessionLocal
import requests
import time
import logging
import asyncio
import aiohttp
from crud import ensure_header_image
import json
import os
from datetime import datetime
from sqlalchemy.sql import or_, and_
import aiofiles
from dotenv import load_dotenv
load_dotenv()

STEAM_API_KEY = os.getenv("STEAM_API_KEY")
MODIFIED_SINCE_FILE = "modified_since.txt"
GET_APP_LIST_URL = "https://api.steampowered.com/IStoreService/GetAppList/v1/"

logging.basicConfig(
    filename="updater.log",
    filemode="w",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

MAX_GENRE_RETRIES = 5
SKIP_FILE = "genre_retry.json"
EXCLUDED_GENRES = {"4", "23", "57", "55", "51"}

UNCERTAIN_DATE_PATTERNS = [
    "To be announced", "Скоро выйдет",
    "Q1", "Q2", "Q3", "Q4"
]

MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December"
]


def is_midnight():
    now = datetime.now()
    return now.hour == 0  # поправил на полночь по локальному времени


def release_date_is_uncertain(date_str):
    if not date_str:
        return False
    if any(date_str.startswith(p) for p in UNCERTAIN_DATE_PATTERNS):
        return True

    parts = date_str.split()
    if len(parts) == 2 and parts[0] in MONTH_NAMES and parts[1].isdigit():
        return True
    return False


def load_genre_retries():
    if os.path.exists(SKIP_FILE):
        with open(SKIP_FILE, "r") as f:
            return json.load(f)
    return {}


def save_genre_retries(retries):
    with open(SKIP_FILE, "w") as f:
        json.dump(retries, f)


def fetch_all_steam_games():
    url = "https://api.steampowered.com/ISteamApps/GetAppList/v2/"
    response = requests.get(url)
    data = response.json()
    apps = data.get("applist", {}).get("apps", [])

    logging.info(f"В базе стима → {len(apps)} игр")
    return apps


def update_games_db():
    db: Session = SyncSessionLocal()
    steam_apps = fetch_all_steam_games()

    existing_ids = {appid for (appid,) in db.query(Release.appid).all()}
    seen_appids = set()
    new_games = []

    for app in steam_apps:
        appid = app["appid"]
        name = app["name"].strip()
        if not name or appid in existing_ids or appid in seen_appids:
            continue
        seen_appids.add(appid)
        new_games.append(Release(appid=appid, name=name, updated_at=datetime.utcnow().isoformat()))

    if new_games:
        db.bulk_save_objects(new_games)
        db.commit()

    db.close()


async def download_header_image(appid: int, session: aiohttp.ClientSession):
    await ensure_header_image(session, appid)


async def update_release_dates():
    db: Session = SyncSessionLocal()
    genre_retries = load_genre_retries()
    skip_appids = [int(appid) for appid, count in genre_retries.items() if count >= MAX_GENRE_RETRIES]

    try:
        async with aiofiles.open(MODIFIED_SINCE_FILE, mode='r') as f:
            if_modified_since = int((await f.read()).strip())
    except Exception:
        if_modified_since = 0

    appids = []
    max_last_modified = if_modified_since

    url = f"{GET_APP_LIST_URL}?key={STEAM_API_KEY}&if_modified_since={if_modified_since}&include_games=1"

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            data = await response.json()

    applist = data.get("response", {}).get("apps", [])
    for app in applist:
        appid = int(app.get("appid"))
        last_modified = app.get("last_modified", 0)
        if appid:
            appids.append(appid)
        if last_modified > max_last_modified:
            max_last_modified = last_modified

    async with aiofiles.open(MODIFIED_SINCE_FILE, mode='w') as f:
        await f.write(str(max_last_modified))

    games_to_update = list(
        db.query(Release)
        .filter(
            Release.type == 'game',
            Release.appid.in_(appids),
            Release.appid.notin_(skip_appids)
        )
        .order_by(Release.appid.desc())
    )

    logging.info(f"Всего отобрано к обновлению: {len(games_to_update)} игр")
    for game in games_to_update:
        if game.appid == 3445830:
            logging.info(f"[DEBUG] Игра 3445830 (Return to Ash) включена в обновление.")

    BATCH_SIZE = 50
    updated = 0
    RETRY_LIMIT = 3
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "DNT": "1",
        "Pragma": "no-cache",
        "Referer": "https://store.steampowered.com/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    }

    async with aiohttp.ClientSession() as session:
        for game in games_to_update:
            changed = False
            appid = game.appid

            if appid == 3445830:
                logging.info(f"[DEBUG] Начинаем обновление appid=3445830 — {game.name}")

            for attempt in range(RETRY_LIMIT):
                try:
                    url = f"https://store.steampowered.com/api/appdetails?appids={appid}&cc=us&l=ru"
                    async with session.get(url, headers=headers, timeout=5) as resp:
                        if resp.status == 429:
                            wait_time = 2 ** attempt
                            logging.warning(f"Steam API вернул 429 для appid={appid}, попытка {attempt+1}, ждём {wait_time} сек")
                            await asyncio.sleep(wait_time)
                            continue
                        elif resp.status == 403:
                            logging.warning(f"Steam API вернул 403 для appid={appid}")
                            if not game.unavailable:
                                game.unavailable = True
                                changed = True
                            break
                        elif resp.status != 200:
                            logging.warning(f"Steam API вернул статус {resp.status} для appid={appid}")
                            break

                        data = await resp.json()
                        app_data = data.get(str(appid), {})
                        if not app_data.get("success"):
                            if appid == 3445830:
                                logging.warning(f"[DEBUG] Steam вернул success=False для 3445830")
                            break

                        details = app_data.get("data", {}) or {}
                        release_info = details.get("release_date", {})
                        new_release_date = release_info.get("date")
                        new_type = details.get("type")
                        genres = details.get("genres", [])
                        new_genres = ",".join(str(g["id"]) for g in genres if "id" in g) if genres else None

                        if genres:
                            genre_retries.pop(str(appid), None)
                        else:
                            genre_retries[str(appid)] = genre_retries.get(str(appid), 0) + 1

                        if game.release_date != new_release_date:
                            game.release_date = new_release_date
                            changed = True
                        if game.type != new_type:
                            game.type = new_type
                            changed = True
                        if game.genres != new_genres:
                            game.genres = new_genres
                            changed = True

                        await download_header_image(appid, session)

                        break  # выход из retry-цикла при успехе

                except Exception as e:
                    logging.error(f"Ошибка при обновлении {appid}: {e}")
                    break

            game.release_date_checked = True
            if changed:
                game.updated_at = datetime.utcnow().isoformat()
                logging.info(f"Обновлено: appid={appid}, name={game.name}")

                if appid == 3445830:
                    logging.info(
                        f"[DEBUG] Успешно обновлено: appid=3445830, дата: {game.release_date}, жанры: {game.genres}, тип: {game.type}")

            db.add(game)
            updated += 1
            if updated % BATCH_SIZE == 0:
                db.commit()

            await asyncio.sleep(2.5)  # увеличенная задержка

        db.commit()
        db.close()
        save_genre_retries(genre_retries)



if __name__ == "__main__":
    asyncio.run(update_release_dates())
