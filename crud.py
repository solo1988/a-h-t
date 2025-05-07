from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from models import Game, Achievement
import logging
from datetime import datetime
import os
import aiohttp
from pathlib import Path

STATIC_DIR = Path(__file__).parent / "static" / "images" / "header"
BACKGROUND_DIR = Path(__file__).parent / "static" / "images" / "background"

async def check_background_exists_local(appid: int) -> bool:
    return (BACKGROUND_DIR / f"{appid}.jpg").exists()

async def ensure_background_image(session: aiohttp.ClientSession, appid: int) -> str:
    BACKGROUND_DIR.mkdir(parents=True, exist_ok=True)
    local_path = BACKGROUND_DIR / f"{appid}.jpg"

    if await check_background_exists_local(appid):
        return f"/static/images/background/{appid}.jpg"

    background_url = f"https://cdn.steamstatic.com/steam/apps/{appid}/library_hero.jpg"
    logging.info(f"[Background] Пробуем скачать background для {appid} из: {background_url}")
    if await download_image(session, background_url, local_path):
        return f"/static/images/background/{appid}.jpg"

    logging.warning(f"[Background] Не удалось получить background для {appid}")
    return ""  # или можно подставить заглушку, если хочешь


async def check_image_exists_local(appid: int) -> bool:
    return (STATIC_DIR / f"{appid}.jpg").exists()

async def download_image(session: aiohttp.ClientSession, url: str, path: Path) -> bool:
    try:
        async with session.get(url) as resp:
            if resp.status == 200:
                with open(path, "wb") as f:
                    f.write(await resp.read())
                logging.info(f"[Загрузка] Скачано изображение: {url}")
                return True
            else:
                logging.warning(f"[Загрузка] Не удалось скачать изображение: {url}, статус {resp.status}")
    except Exception as e:
        logging.error(f"[Ошибка загрузки] {url} — {e}")
    return False

async def get_header_image_url_from_api(session: aiohttp.ClientSession, appid: int) -> str:
    api_url = f"https://store.steampowered.com/api/appdetails?appids={appid}"
    try:
        async with session.get(api_url) as resp:
            if resp.status == 200:
                data = await resp.json()
                entry = data.get(str(appid), {})
                if entry.get("success") and "data" in entry:
                    return entry["data"].get("header_image", "")
    except Exception as e:
        logging.error(f"[Steam API] Ошибка получения header_image для {appid}: {e}")
    return ""

async def ensure_header_image(session: aiohttp.ClientSession, appid: int) -> str:
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    local_path = STATIC_DIR / f"{appid}.jpg"
    if await check_image_exists_local(appid):
        return f"/static/images/header/{appid}.jpg"

    # 1. Пробуем CDN
    cdn_url = f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/header.jpg"
    if await download_image(session, cdn_url, local_path):
        return f"/static/images/header/{appid}.jpg"

    # 2. Пробуем Steam API
    logging.info(f"[API] Пробуем получить header_image для {appid}")
    header_url = await get_header_image_url_from_api(session, appid)
    if header_url:
        logging.info(f"[API] Найден header_image из Steam API для {appid}: {header_url}")

    if header_url and await download_image(session, header_url, local_path):
        return f"/static/images/header/{appid}.jpg"

    logging.warning(f"[Фон] Не удалось получить header для {appid}")
    return ""  # можно подставить заглушку


# Получение всех игр из базы данных
async def get_games(db: AsyncSession, id: int):
    try:
        result = await db.execute(select(Game).filter(Game.user_id == id))
        games = result.scalars().all()
        logging.info(f"Получены игры : {games}")
        print(f"Fetched games: {games}")  # Логируем все игры

        async with aiohttp.ClientSession() as session:
            for game in games:
                total_achievements = await get_total_achievements_for_game(db, game.appid, id)
                earned_achievements = await get_earned_achievements_for_game(db, game.appid, id)
                last_obtained_date = await get_last_obtained_date_for_game(db, game.appid, id)
                logging.info(f"Игра {game.name} - Всего достижений: {total_achievements}, получено достижений: {earned_achievements}")
                print(f"Game {game.name} - Total Achievements: {total_achievements}, Earned Achievements: {earned_achievements}")  # Логируем достижения для каждой игры

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
        logging.error(f"Ошибка при выборке игр: {str(e)}")
        print(f"Error while fetching games: {str(e)}")
        raise e

# Получение самой свежей ачивки
async def get_last_obtained_date_for_game(db: AsyncSession, appid: int, id: int):
    result = await db.execute(
        select(func.max(Achievement.obtained_date))
        .where(Achievement.appid == appid).where(Achievement.user_id == id)
        .where(Achievement.obtained_date != "0")
    )
    return result.scalar_one_or_none()

# Получение названия игры
async def get_game_name(db: AsyncSession, appid: int, id: int):
    result = await db.execute(select(Game).filter(Game.appid == appid).filter(Game.user_id == id))
    name = result.scalars().one()
    return name

# Получение всех достижений для игры по appid
async def get_achievements_for_game(db: AsyncSession, appid: int, id: int):
    result = await db.execute(select(Achievement).filter(Achievement.appid == appid).filter(Achievement.user_id == id))
    achievements = result.scalars().all()
    return achievements

# Получение общего количества достижений для игры
async def get_total_achievements_for_game(db: AsyncSession, appid: int, id: int):
    try:
        result = await db.execute(select(Achievement).filter(Achievement.appid == appid).filter(Achievement.user_id == id))
        achievements = result.scalars().all()
        logging.info(f"Всего достижений для appid {appid}: {len(achievements)}")
        print(f"Total achievements for appid {appid}: {len(achievements)}")  # Логируем общее количество достижений
        return len(achievements)
    except Exception as e:
        logging.error(f"Ошибка при выборке ачивок для игры appid {appid}: {str(e)}")
        print(f"Error while fetching total achievements for appid {appid}: {str(e)}")
        raise e

# Получение количества полученных достижений для игры
from sqlalchemy import func

async def get_earned_achievements_for_game(db: AsyncSession, appid: int, id: int):
    try:
        result = await db.execute(
            select(func.count(Achievement.id))
            .filter(Achievement.appid == appid).filter(Achievement.user_id == id)
            .filter(Achievement.obtained_date != None)  # Фильтрация по полученным достижениям
        )
        earned_achievements = result.scalar_one()  # Получаем количество
        logging.info(f"Получено ачивок для игры appid {appid}: {earned_achievements}")
        print(f"Earned achievements for appid {appid}: {earned_achievements}")  # Логируем количество полученных достижений
        return earned_achievements
    except Exception as e:
        logging.error(f"Ошибка при выборке полученных ачивок для игры appid {appid}: {str(e)}")
        print(f"Error while fetching earned achievements for appid {appid}: {str(e)}")
        raise e
