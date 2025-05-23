from sqlalchemy.orm import Session
from models import Release
from database import SyncSessionLocal
import requests
import time
import logging
from sqlalchemy import null
import asyncio
import aiohttp
from crud import ensure_header_image

logging.basicConfig(
    filename="updater.log",  # Имя файла для записи логов
    level=logging.INFO,  # Уровень логирования
    format="%(asctime)s - %(levelname)s - %(message)s",  # Формат сообщений
)


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

    # Получаем уже существующие appid
    existing_ids = {appid for (appid,) in db.query(Release.appid).all()}

    # Чтобы избежать повторов в самом списке Steam
    seen_appids = set()

    new_games = []
    for app in steam_apps:
        appid = app["appid"]
        name = app["name"].strip()

        if not name or appid in existing_ids or appid in seen_appids:
            continue

        seen_appids.add(appid)
        new_games.append(Release(appid=appid, name=name))
    if new_games:
        db.bulk_save_objects(new_games)
        db.commit()

    db.close()



def update_release_dates():
    db: Session = SyncSessionLocal()

    games_to_update = db.query(Release).filter(Release.genres.is_(None)).all()

    BATCH_SIZE = 50
    updated = 0

    for game in games_to_update:
        url = f"https://store.steampowered.com/api/appdetails?appids={game.appid}"
        try:
            resp = requests.get(url, timeout=5)
            data = resp.json()

            app_data = data.get(str(game.appid), {})
            if app_data.get("success"):
                details = app_data.get("data", {})
                release_info = details.get("release_date", {})

                game.release_date = release_info.get("date")
                game.type = details.get("type")

                # Извлекаем жанры
                genres = details.get("genres", [])
                if genres:
                    genre_ids = [str(g["id"]) for g in genres if "id" in g]
                    game.genres = ",".join(genre_ids)

                # Скачиваем header image
                asyncio.run(download_header_image(game.appid))
        except Exception as e:
            print(f"Ошибка при обновлении {game.appid}: {e}")

        game.release_date_checked = True
        db.add(game)
        updated += 1

        if updated % BATCH_SIZE == 0:
            db.commit()
            logging.info(f"Сохранено {updated} записей")

        time.sleep(1)

    db.commit()
    db.close()


async def download_header_image(appid: int):
    async with aiohttp.ClientSession() as session:
        await ensure_header_image(session, appid)