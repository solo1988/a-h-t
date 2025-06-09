from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from models import Game, Achievement, Release
import logging
# from datetime import datetime
from datetime import datetime, date
import os
import aiohttp
from pathlib import Path
from dateutil import parser
from collections import defaultdict
from sqlalchemy import not_, or_, func, literal
from typing import Optional, Union
import re

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
    #logging.info(f"[Background] Пробуем скачать background для {appid} из: {background_url}")
    if await download_image(session, background_url, local_path):
        return f"/static/images/background/{appid}.jpg"

    #logging.warning(f"[Background] Не удалось получить background для {appid}")
    return ""  # или можно подставить заглушку, если хочешь


async def check_image_exists_local(appid: int) -> bool:
    return (STATIC_DIR / f"{appid}.jpg").exists()


async def download_image(session: aiohttp.ClientSession, url: str, path: Path) -> bool:
    try:
        async with session.get(url) as resp:
            if resp.status == 200:
                with open(path, "wb") as f:
                    f.write(await resp.read())
                #logging.info(f"[Загрузка] Скачано изображение: {url}")
                return True
            else:
                #logging.error(f"[Загрузка] Не удалось скачать изображение: {url}, статус {resp.status}")
                print(f"[Загрузка] Не удалось скачать изображение: {url}, статус {resp.status}")
    except Exception as e:
        #logging.error(f"[Ошибка загрузки] {url} — {e}")
        print(f"[Ошибка загрузки] {url} — {e}")
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
    #logging.info(f"[API] Пробуем получить header_image для {appid}")
    header_url = await get_header_image_url_from_api(session, appid)
    if header_url:
        #logging.info(f"[API] Найден header_image из Steam API для {appid}: {header_url}")
        print(f"[API] Найден header_image из Steam API для {appid}: {header_url}")

    if header_url and await download_image(session, header_url, local_path):
        return f"/static/images/header/{appid}.jpg"

    #logging.warning(f"[Фон] Не удалось получить header для {appid}")
    return ""  # можно подставить заглушку


MONTHS_MAP = {
    1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
    7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec"
}

RUSSIAN_MONTHS = {
    'января': 1, 'февраля': 2, 'марта': 3, 'апреля': 4, 'мая': 5, 'июня': 6,
    'июля': 7, 'августа': 8, 'сентября': 9, 'октября': 10, 'ноября': 11, 'декабря': 12,
    'янв.': 1, 'февр.': 2, 'марта': 3, 'апр.': 4, 'мая': 5, 'июн.': 6,
    'июл.': 7, 'авг.': 8, 'сент.': 9, 'окт.': 10, 'нояб.': 11, 'дек.': 12,
    'янв': 1, 'февр': 2, 'мар': 3, 'апр': 4, 'май': 5, 'июн': 6,
    'июл': 7, 'авг': 8, 'сент': 9, 'окт': 10, 'нояб': 11, 'дек': 12,
    'январь': 1, 'февраль': 2, 'март': 3, 'апрель': 4, 'май': 5, 'июнь': 6,
    'июль': 7, 'август': 8, 'сентябрь': 9, 'октябрь': 10, 'ноябрь': 11, 'декабрь': 12,
}

def parse_release_date(date_str: str):

    date_str = date_str.strip().lower()
    date_str = re.sub(r'\s*г\.?$', '', date_str).strip()
    date_str = date_str.replace('\xa0', ' ')  # <--- добавь это


    # Английские форматы с днем
    for fmt in ("%d %b, %Y", "%b %d, %Y", "%d %B, %Y", "%B %d, %Y"):
        try:
            parsed = datetime.strptime(date_str, fmt)
            return parsed.date()
        except ValueError:
            continue

    # Английские форматы только месяц и год
    for fmt in ("%b %Y", "%B %Y"):
        try:
            parsed = datetime.strptime(date_str, fmt)
            return date(parsed.year, parsed.month, 1)
        except ValueError:
            continue

    # Русские форматы с числом
    match = re.match(r'(\d{1,2})\s+([а-яё]+)\.?\s+(\d{4})', date_str)
    if match:
        day, month_name, year = match.groups()
        month_key = month_name.strip()

        month = RUSSIAN_MONTHS.get(month_key)
        if month:
            try:
                return date(int(year), month, int(day))
            except ValueError:
                pass

    # Русские форматы без числа (только месяц и год)
    match = re.match(r'([а-яё.]+)\s+(\d{4})', date_str)
    if match:
        month_name, year = match.groups()
        month = RUSSIAN_MONTHS.get(month_name.strip())
        if month:
            return date(int(year), month, 1)

    # Кварталы английские, например Q1 2025
    match = re.match(r'q([1-4])\s+(\d{4})', date_str)
    if match:
        quarter, year = match.groups()
        month = (int(quarter) - 1) * 3 + 1
        return date(int(year), month, 1)

    # Кварталы русские, например 1 квартал 2025
    match = re.match(r'(\d)\s*квартал\s*(\d{4})', date_str)
    if match:
        quarter, year = match.groups()
        month = (int(quarter) - 1) * 3 + 1
        return date(int(year), month, 1)

    # Просто год
    match = re.match(r'(\d{4})', date_str)
    if match:
        year = int(match.group(1))
        return date(year, 1, 1)

    return None


# Получение релизов за месяц или за конкретный день
async def get_releases(
        db: AsyncSession,
        year: int,
        month: int,
        user_id: int,
        day: Optional[int] = None
) -> Union[defaultdict, list]:
    try:
        month_str = MONTHS_MAP.get(month)
        if not month_str:
            raise ValueError(f"Invalid month number: {month}")

        excluded_genres = ['4', '23', '57', '55', '51']
        wrapped_genres = literal(',') + Release.genres + literal(',')

        excluded_conditions = [
            wrapped_genres.like(f'%,{genre},%') for genre in excluded_genres
        ]

        EN_MONTHS_ABBR = {
            1: 'Jan', 2: 'Feb', 3: 'Mar', 4: 'Apr', 5: 'May', 6: 'Jun',
            7: 'Jul', 8: 'Aug', 9: 'Sep', 10: 'Oct', 11: 'Nov', 12: 'Dec'
        }

        FULL_EN_MONTHS = {
            1: 'January', 2: 'February', 3: 'March', 4: 'April', 5: 'May',
            6: 'June', 7: 'July', 8: 'August', 9: 'September', 10: 'October',
            11: 'November', 12: 'December'
        }

        FULL_RU_MONTHS = {
            1: 'Января', 2: 'Февраля', 3: 'Марта', 4: 'Апреля', 5: 'Мая',
            6: 'Июня', 7: 'Июля', 8: 'Августа', 9: 'Сентября', 10: 'Октября',
            11: 'Ноября', 12: 'Декабря'
        }

        RU_MONTHS_ABBR = {
            1: 'янв.', 2: 'февр.', 3: 'мар.', 4: 'апр.', 5: 'мая', 6: 'июн.',
            7: 'июл.', 8: 'авг.', 9: 'сент.', 10: 'окт.', 11: 'нояб.', 12: 'дек.'
        }

        ru_month_str = RU_MONTHS_ABBR.get(month)
        like_pattern_ru_dot = f"%{ru_month_str} {year}%"  # пример: "%авг. 2014%"
        like_pattern_ru_year_suffix = f"%{ru_month_str} {year} г.%"  # пример: "%авг. 2014 г.%"

        month_str_full = FULL_EN_MONTHS.get(month)
        like_pattern_full_eng_space = f"%{month_str_full} {year}%"
        like_pattern_full_eng_comma = f"%{month_str_full}, {year}%"

        ru_month_str_full = FULL_RU_MONTHS.get(month)
        like_pattern_full_ru_space = f"%{ru_month_str_full} {year}%"
        like_pattern_full_ru_comma = f"%{ru_month_str_full}, {year}%"

        month_str_eng = EN_MONTHS_ABBR.get(month)
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
        logging.error(f"Ошибка при выборке релизов: {str(e)}")
        raise


# Получение всех игр из базы данных
async def get_games(db: AsyncSession, id: int):
    try:
        result = await db.execute(select(Game).filter(Game.user_id == id))
        games = result.scalars().all()
        # logging.info(f"Получены игры : {games}")
        print(f"Fetched games: {games}")  # Логируем все игры

        async with aiohttp.ClientSession() as session:
            for game in games:
                total_achievements = await get_total_achievements_for_game(db, game.appid, id)
                earned_achievements = await get_earned_achievements_for_game(db, game.appid, id)
                last_obtained_date = await get_last_obtained_date_for_game(db, game.appid, id)
                # logging.info(f"Игра {game.name} - Всего достижений: {total_achievements}, получено достижений: {earned_achievements}")
                print(
                    f"Game {game.name} - Total Achievements: {total_achievements}, Earned Achievements: {earned_achievements}")  # Логируем достижения для каждой игры

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
    result = await db.execute(select(Release).filter(Release.appid == appid))
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
        result = await db.execute(
            select(Achievement).filter(Achievement.appid == appid).filter(Achievement.user_id == id))
        achievements = result.scalars().all()
        # logging.info(f"Всего достижений для appid {appid}: {len(achievements)}")
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
        # logging.info(f"Получено ачивок для игры appid {appid}: {earned_achievements}")
        print(
            f"Earned achievements for appid {appid}: {earned_achievements}")  # Логируем количество полученных достижений
        return earned_achievements
    except Exception as e:
        logging.error(f"Ошибка при выборке полученных ачивок для игры appid {appid}: {str(e)}")
        print(f"Error while fetching earned achievements for appid {appid}: {str(e)}")
        raise e
