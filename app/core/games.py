from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, Union
from collections import defaultdict
from app.models import Game, Release, Favorite, Wanted
from sqlalchemy import not_, or_, func, literal
from sqlalchemy.future import select
from datetime import datetime, date
import aiohttp
import aiofiles
import asyncio
import requests
import logging
import urllib.parse
import time
import httpx
from sqlalchemy.orm import Session, selectinload
from app.core.database import SyncSessionLocal, SessionLocal

from app.core.images import ensure_header_image, ensure_background_image, download_header_image
from app.core.achievements import get_last_obtained_date_for_game, get_total_achievements_for_game, \
    get_earned_achievements_for_game
from app.core.config import settings
from app.core.dates import parse_release_date, parse_release_date_fav
from app.core.files import load_genre_retries, save_genre_retries
from app.core.logger import logger, logger_update
from app.core.telegram import send_telegram_message_with_image_async



# Получение релизов за месяц или за конкретный день
async def get_releases(db: AsyncSession, year: int, month: int, user_id: int, day: Optional[int] = None
                       ) -> Union[defaultdict, list]:
    try:
        month_str = settings.MONTHS_MAP.get(month)
        if not month_str:
            raise ValueError(f"Invalid month number: {month}")

        wrapped_genres = literal(',') + Release.genres + literal(',')

        excluded_conditions = [
            wrapped_genres.like(f'%,{genre},%') for genre in settings.EXCLUDED_GENRES
        ]

        ru_month_str = settings.RU_MONTHS_ABBR.get(month)
        like_pattern_ru_dot = f"%{ru_month_str} {year}%"  # пример: "%авг. 2014%"
        like_pattern_ru_year_suffix = f"%{ru_month_str} {year} г.%"  # пример: "%авг. 2014 г.%"

        month_str_full = settings.FULL_EN_MONTHS.get(month)
        like_pattern_full_eng_space = f"%{month_str_full} {year}%"
        like_pattern_full_eng_comma = f"%{month_str_full}, {year}%"

        ru_month_str_full = settings.FULL_RU_MONTHS.get(month)
        like_pattern_full_ru_space = f"%{ru_month_str_full} {year}%"
        like_pattern_full_ru_comma = f"%{ru_month_str_full}, {year}%"

        month_str_eng = settings.EN_MONTHS_ABBR.get(month)
        if not month_str_eng:
            raise ValueError(f"Invalid month number: {month}")

        like_pattern_eng = f"{month_str_eng} %, {year}"  # например "Jun %, 2025"

        like_pattern_comma = f"%{month_str}, {year}%"
        like_pattern_no_comma = f"%{month_str} {year}%"

        stmt = (
            select(Release)
            .filter(Release.release_date_checked == 1)
            .filter(Release.type == 'game')
            .filter(
                or_(
                    Release.release_date.like(like_pattern_comma),
                    Release.release_date.like(like_pattern_no_comma),
                    Release.release_date.like(f"%{like_pattern_eng}%"),
                    Release.release_date.like(like_pattern_full_eng_space),
                    Release.release_date.like(like_pattern_full_eng_comma),
                    Release.release_date.like(like_pattern_full_ru_space),
                    Release.release_date.like(like_pattern_full_ru_comma),
                    Release.release_date.like(like_pattern_ru_dot),
                    Release.release_date.like(like_pattern_ru_year_suffix)
                )
            )
            .filter(not_(or_(*excluded_conditions)))
        )

        result = await db.execute(stmt)
        releases = result.scalars().all()

        if day:
            # Фильтруем релизы только за указанный день
            selected_date = date(year, month, day)
            daily_releases = []
            for rel in releases:
                parsed = parse_release_date(rel.release_date)
                if parsed and parsed == selected_date:
                    daily_releases.append(rel)
            return daily_releases

        # Вернуть по дням для календаря
        calendar_data = defaultdict(list)
        for rel in releases:
            parsed = parse_release_date(rel.release_date)
            if parsed:
                calendar_data[parsed].append(rel)
            else:
                calendar_data["no_date"].append(rel)

        return calendar_data

    except Exception as e:
        raise


# Получение всех игр из базы данных
async def get_games(db: AsyncSession, id: int):
    try:
        result = await db.execute(select(Game).filter(Game.user_id == id))
        games = result.scalars().all()

        async with aiohttp.ClientSession() as session:
            for game in games:
                total_achievements = await get_total_achievements_for_game(db, game.appid, id)
                earned_achievements = await get_earned_achievements_for_game(db, game.appid, id)
                last_obtained_date = await get_last_obtained_date_for_game(db, game.appid, id)

                game.total_achievements = total_achievements
                game.earned_achievements = earned_achievements

                if isinstance(last_obtained_date, str):
                    game.last_obtained_date = datetime.fromisoformat(last_obtained_date)
                else:
                    game.last_obtained_date = last_obtained_date or datetime(1970, 1, 1)

                # Загружаем или подставляем локальный header
                game.background = await ensure_header_image(session, game.appid)
                await ensure_background_image(session, game.appid)

        # Сортируем по дате получения
        games.sort(key=lambda g: g.last_obtained_date, reverse=True)

        return games

    except Exception as e:
        print(f"Error while fetching games: {str(e)}")
        raise e


# Получение названия игры
async def get_game_name(db: AsyncSession, appid: int, id: int):
    result = await db.execute(select(Release).filter(Release.appid == appid))
    name = result.scalars().one()
    return name


# Все игры из стима
def fetch_all_steam_games():
    response = requests.get(settings.FETCH_APP_URL)
    data = response.json()
    apps = data.get("applist", {}).get("apps", [])

    logging.info(f"В базе стима → {len(apps)} игр")
    return apps


# Обновление релизов в базе
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


# Обновление дат релизов
async def update_release_dates():
    db: Session = SyncSessionLocal()
    genre_retries = load_genre_retries()
    skip_appids = [int(appid) for appid, count in genre_retries.items() if count >= settings.MAX_GENRE_RETRIES]

    try:
        async with aiofiles.open(settings.MODIFIED_SINCE_FILE, mode='r') as f:
            if_modified_since = int((await f.read()).strip())
    except Exception:
        if_modified_since = 0

    appids = []
    max_last_modified = if_modified_since

    url = f"{settings.GET_APP_LIST_URL}?key={settings.STEAM_API_KEY}&if_modified_since={if_modified_since}&include_games=1"

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

    async with aiofiles.open(settings.MODIFIED_SINCE_FILE, mode='w') as f:
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

    logger_update.info(f"Всего отобрано к обновлению: {len(games_to_update)} игр")
    for game in games_to_update:
        if game.appid == 3445830:
            logger_update.info(f"[DEBUG] Игра 3445830 (Return to Ash) включена в обновление.")

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
                logger_update.info(f"[DEBUG] Начинаем обновление appid=3445830 — {game.name}")

            for attempt in range(RETRY_LIMIT):
                try:
                    url = f"https://store.steampowered.com/api/appdetails?appids={appid}&cc=us&l=ru"
                    async with session.get(url, headers=headers, timeout=5) as resp:
                        if resp.status == 429:
                            wait_time = 2 ** attempt
                            logger_update.warning(f"Steam API вернул 429 для appid={appid}, попытка {attempt+1}, ждём {wait_time} сек")
                            await asyncio.sleep(wait_time)
                            continue
                        elif resp.status == 403:
                            logger_update.warning(f"Steam API вернул 403 для appid={appid}")
                            if not game.unavailable:
                                game.unavailable = True
                                changed = True
                            break
                        elif resp.status != 200:
                            logger_update.warning(f"Steam API вернул статус {resp.status} для appid={appid}")
                            break

                        data = await resp.json()
                        app_data = data.get(str(appid), {})
                        if not app_data.get("success"):
                            if appid == 3445830:
                                logger_update.warning(f"[DEBUG] Steam вернул success=False для 3445830")
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
                    logger_update.error(f"Ошибка при обновлении {appid}: {e}")
                    break

            game.release_date_checked = True
            if changed:
                game.updated_at = datetime.utcnow().isoformat()
                logger_update.info(f"Обновлено: appid={appid}, name={game.name}")

                if appid == 3445830:
                    logger_update.info(
                        f"[DEBUG] Успешно обновлено: appid=3445830, дата: {game.release_date}, жанры: {game.genres}, тип: {game.type}")

            db.add(game)
            updated += 1
            if updated % BATCH_SIZE == 0:
                db.commit()

            await asyncio.sleep(2.5)  # увеличенная задержка

        db.commit()
        db.close()
        save_genre_retries(genre_retries)


# Получение избранного юзера
async def get_user_favorites(user_id: int, session: AsyncSession) -> list[int]:
    query = select(Favorite.appid).where(Favorite.user_id == user_id)
    result = await session.execute(query)
    return [row[0] for row in result.fetchall()]


# Проверка релизов на сегодня
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
            parsed_date = parse_release_date_fav(release.release_date)
            if parsed_date == today:
                releases_by_user.setdefault(fav.user_id, []).append(release)

        if not releases_by_user:
            logger.info("[check_favorites] Сегодня нет релизов в избранных играх.")
            return

        user_names = {1: "Слава", 2: "Коля"}

        for user_id, releases in releases_by_user.items():
            telegram_id = settings.USER_TO_TELEGRAM_ID.get(user_id)
            if telegram_id is None or telegram_id not in settings.TELEGRAM_IDS:
                continue

            game_names = ', '.join(rel.name for rel in releases)
            user_name = user_names.get(user_id, f"user_id={user_id}")
            logger.info(f"[check_favorites] Выходят релизы из избранного пользователя {user_name}: {game_names}")

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
                        telegram_id, message, settings.BOT_TOKEN, image_url, buttons
                    )
                except Exception as e:
                    print(f"[check_favorites] Исключение при отправке сообщения пользователю {telegram_id}: {e}")


# Проверка и сохранение самых ожидаемых игр
def fetch_and_store_wanted():
    current_year = datetime.date.today().year
    session: Session = SyncSessionLocal()

    try:
        page = 1
        while True:
            response = requests.get(settings.RAWG_URL, params={
                "platforms": 4,
                "dates": f"{current_year}-01-01,{current_year}-12-31",
                "ordering": "-added",
                "page_size": 40,
                "page": page,
                "key": settings.RAWG_API_KEY
            })
            data = response.json()
            games = data.get("results", [])
            if not games:
                print("Данные закончились, игр нет на странице", page)
                break

            any_added = False
            for game in games:
                if game["added"] > 0:
                    any_added = True
                    release_date_str = game["released"]
                    if release_date_str:
                        try:
                            release_date = datetime.datetime.strptime(release_date_str, "%Y-%m-%d").date()
                        except ValueError:
                            release_date = None
                    else:
                        release_date = None

                    wanted_game = session.query(Wanted).filter(func.lower(Wanted.name) == game["name"].lower()).first()
                    if wanted_game:
                        updated = False
                        if wanted_game.added != game["added"]:
                            wanted_game.added = game["added"]
                            updated = True
                        if wanted_game.release_date != release_date:
                            wanted_game.release_date = release_date
                            updated = True
                        if updated:
                            print(f"Обновлена игра: {game['name']}, added: {game['added']}")
                    else:
                        wanted = Wanted(
                            name=game["name"],
                            rawg_id=game["id"],
                            added=game["added"],
                            release_date=release_date
                        )
                        session.add(wanted)
                        print(f"Добавлена новая игра: {game['name']}, added: {game['added']}")
                else:
                    continue

            session.commit()

            if not any_added:
                print(f"Достигли конца на странице {page} — все игры с added == 0.")
                break

            print(f"Обработана страница {page}, игр с added > 0: {sum(1 for g in games if g['added'] > 0)}")
            page += 1
            time.sleep(1)

        # Подставляем appid из releases по совпадению имени (без учета регистра)
        wanted_games = session.query(Wanted).filter(Wanted.appid.is_(None)).all()
        for wanted in wanted_games:
            release = session.query(Release).filter(func.lower(Release.name) == wanted.name.lower()).first()
            if release:
                wanted.appid = release.appid

        session.commit()

    finally:
        session.close()


# Возврат данных игры со стима
async def fetch_game_data(appid: int):
    async with httpx.AsyncClient() as client:
        url = f"{settings.STEAM_API_URL}?key={settings.STEAM_API_KEY}&appid={appid}"
        response = await client.get(url)
        if response.status_code == 200:
            game_data = response.json()
            return game_data
    return None