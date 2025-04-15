from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from models import Game, Achievement
import logging
from datetime import datetime

# Получение всех игр из базы данных
async def get_games(db: AsyncSession):
    try:
        result = await db.execute(select(Game))
        games = result.scalars().all()
        logging.info(f"Получены игры : {games}")
        print(f"Fetched games: {games}")  # Логируем все игры

        for game in games:
            total_achievements = await get_total_achievements_for_game(db, game.appid)
            earned_achievements = await get_earned_achievements_for_game(db, game.appid)
            last_obtained_date = await get_last_obtained_date_for_game(db, game.appid)
            logging.info(f"Игра {game.name} - Всего достижений: {total_achievements}, получено достижений: {earned_achievements}")
            print(f"Game {game.name} - Total Achievements: {total_achievements}, Earned Achievements: {earned_achievements}")  # Логируем достижения для каждой игры
            game.total_achievements = total_achievements
            game.earned_achievements = earned_achievements
            # Преобразуем строку в datetime, если это строка
            if isinstance(last_obtained_date, str):
                game.last_obtained_date = datetime.fromisoformat(last_obtained_date)
            else:
                game.last_obtained_date = last_obtained_date or datetime(1970, 1, 1)  # Используем минимальную дату, если нет данных
            game.background = f"https://cdn.cloudflare.steamstatic.com/steam/apps/{game.appid}/header.jpg"

        # Сортируем по last_obtained_date, новейшие — первыми
        games.sort(key=lambda g: g.last_obtained_date, reverse=True)

        return games
    except Exception as e:
        logging.error(f"Ошибка при выборке игр: {str(e)}")
        print(f"Error while fetching games: {str(e)}")
        raise e

# Получение самой свежей ачивки
async def get_last_obtained_date_for_game(db: AsyncSession, appid: int):
    result = await db.execute(
        select(func.max(Achievement.obtained_date))
        .where(Achievement.appid == appid)
        .where(Achievement.obtained_date != "0")
    )
    return result.scalar_one_or_none()

# Получение названия игры
async def get_game_name(db: AsyncSession, appid: int):
    result = await db.execute(select(Game).filter(Game.appid == appid))
    name = result.scalars().one()
    return name

# Получение всех достижений для игры по appid
async def get_achievements_for_game(db: AsyncSession, appid: int):
    result = await db.execute(select(Achievement).filter(Achievement.appid == appid))
    achievements = result.scalars().all()
    return achievements

# Получение общего количества достижений для игры
async def get_total_achievements_for_game(db: AsyncSession, appid: int):
    try:
        result = await db.execute(select(Achievement).filter(Achievement.appid == appid))
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

async def get_earned_achievements_for_game(db: AsyncSession, appid: int):
    try:
        result = await db.execute(
            select(func.count(Achievement.id))
            .filter(Achievement.appid == appid)
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
