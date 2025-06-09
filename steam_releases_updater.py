from sqlalchemy.orm import Session
from models import Release
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
from sqlalchemy import or_, and_

logging.basicConfig(
    filename="updater.log",
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
    return now.hour == 14

def release_date_is_uncertain(date_str):
    if not date_str:
        return False
    if any(date_str.startswith(q) for q in UNCERTAIN_DATE_PATTERNS):
        return True
    if any(month in date_str for month in MONTH_NAMES):
        parts = date_str.split()
        return len(parts) == 2 and parts[0] in MONTH_NAMES and parts[1].isdigit()
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
    print(f"В базе стима → {len(apps)} игр")
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
        logging.info(
            f"Добавлена новая игра: appid={appid}, name='{name}'"
        )

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

    # Основной запрос: всё, что требует обновления
    base_query = db.query(Release).filter(
        Release.unavailable.is_(False),  # исключить помеченные
        or_(
            and_(
                Release.release_date_checked.is_(True),
                Release.genres.is_(None),
                Release.type == 'game',
                ~Release.appid.in_(skip_appids)
            ),
            and_(
                Release.release_date_checked.is_(False)
            ),
            and_(
                Release.type.is_(None)
            )
        )
    ).order_by(Release.appid.desc())

    games_to_update = list(base_query)

    # Добавить дополнительные игры с неопределённой датой, если сейчас полночь
    if is_midnight():
        midnight_candidates = db.query(Release).filter(
            Release.type == 'game',
            Release.release_date.isnot(None)
        ).order_by(Release.appid.desc()).all()

        existing_appids = {g.appid for g in games_to_update}

        for game in midnight_candidates:
            genres = set((game.genres or "").split(","))
            if any(g in EXCLUDED_GENRES for g in genres):
                continue

            if release_date_is_uncertain(game.release_date):
                if game.appid not in existing_appids:
                    games_to_update.append(game)
                    existing_appids.add(game.appid)
                    logging.info(
                        f"Добавлена игра с неопределённой датой релиза: appid={game.appid}, name='{game.name}', release_date='{game.release_date}'"
                    )

    BATCH_SIZE = 50
    updated = 0

    headers = {
        "Accept-Language": "ru",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache"
    }

    async with aiohttp.ClientSession() as session:
        for game in games_to_update:
            url = f"https://store.steampowered.com/api/appdetails?appids={game.appid}&cc=us&l=ru"
            try:
                async with session.get(url, headers=headers, timeout=5) as resp:
                    data = await resp.json()

                    app_data = data.get(str(game.appid), {})
                    if app_data.get("success"):
                        details = app_data.get("data", {})
                        if not details:
                            logging.info(f"appid={game.appid} вернул пустые данные при success=True")
                            continue
                        release_info = details.get("release_date", {})

                        game.release_date = release_info.get("date")
                        game.type = details.get("type")

                        genres = details.get("genres", [])
                        if genres:
                            genre_ids = [str(g["id"]) for g in genres if "id" in g]
                            game.genres = ",".join(genre_ids)
                            genre_retries.pop(str(game.appid), None)
                        else:
                            genre_retries[str(game.appid)] = genre_retries.get(str(game.appid), 0) + 1

                        await download_header_image(game.appid, session)
                    else:
                        game.unavailable = True
                        game.release_date_checked = True
                        game.updated_at = datetime.utcnow().isoformat()
                        db.add(game)
                        updated += 1  # если хочешь учитывать их тоже
                        if updated % BATCH_SIZE == 0:
                            db.commit()
                            #logging.info(f"Сохранено {updated} записей")
                        continue

            except Exception as e:
                print(f"Ошибка при обновлении {game.appid}: {e}")

            game.release_date_checked = True
            game.updated_at = datetime.utcnow().isoformat()  # <-- добавлено
            db.add(game)
            updated += 1

            if updated % BATCH_SIZE == 0:
                db.commit()
                #logging.info(f"Сохранено {updated} записей")

            await asyncio.sleep(1)

        db.commit()
        db.close()
        save_genre_retries(genre_retries)

if __name__ == "__main__":
    asyncio.run(update_release_dates())
