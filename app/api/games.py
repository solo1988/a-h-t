import httpx
from fastapi import APIRouter, Request, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.future import select
from sqlalchemy import text, or_, cast, String

from app.core.auth import manager
from app.core.database import SessionLocal
from app.models import Game, Achievement, Favorite, Release
from app.core.games import fetch_game_data
from app.core.achievements import get_achievement_url
from app.core.logger import logger_app

router = APIRouter()

# Добавление игры
@router.post("/add_game")
async def add_game(request: Request, user=Depends(manager)):
    async with SessionLocal() as db:
        data = await request.json()
        logger_app.info(f"Получены данные игры: {data}")

        try:
            appid = int(data["appid"])
        except (KeyError, ValueError):
            raise HTTPException(status_code=400, detail="Некорректный формат appid")

        logger_app.info(f"Спарсили appid: {appid}")

        existing_game = await db.execute(select(Game).filter(Game.appid == appid).filter(Game.user_id == user.id))
        if existing_game.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Игра уже добавлена")

        game_data = await fetch_game_data(appid)
        if not game_data or "game" not in game_data:
            raise HTTPException(status_code=404, detail="Игра не найдена в Steam")

        game_name = game_data["game"]["gameName"]
        new_game = Game(appid=appid, name=game_name, user_id=user.id)
        db.add(new_game)

        achievements = game_data["game"].get("availableGameStats", {}).get("achievements", [])
        for ach in achievements:
            icongray_url = await get_achievement_url(game_name, ach["displayName"])
            achievement = Achievement(
                appid=appid,
                name=ach["name"],
                displayname=ach["displayName"],
                defaultval=ach.get("defaultValue", 0),
                hidden=ach.get("hidden", 0),
                icon=ach.get("icon", ""),
                icongray=icongray_url,
                obtained_date=None,
                user_id=user.id,
            )
            db.add(achievement)

        try:
            await db.commit()
            logger_app.info("Игра и достижения добавлены")
            return {"message": "Игра и достижения добавлены"}
        except IntegrityError:
            await db.rollback()
            raise HTTPException(status_code=500, detail="Ошибка при добавлении игры")
        finally:
            logger_app.info("-" * 60)

# Обновление путей вручную для stratege
@router.post("/update_paths")
async def update_paths(request: Request, user=Depends(manager)):
    async with SessionLocal() as db:
        data = await request.json()
        logger_app.info(f"Получили данные по игре: {data}")

        appid = data.get("appid")
        old_substring = data.get("oldSubstring")
        new_substring = data.get("newSubstring")

        if not all([appid, old_substring, new_substring]):
            raise HTTPException(status_code=400, detail="Все поля должны быть заполнены")

        try:
            appid = int(appid)
        except ValueError:
            raise HTTPException(status_code=400, detail="Некорректный формат appid")

        logger_app.info(f"Спарсили успешно: {appid}")

        try:
            query = text("""
                UPDATE achievements
                SET icongray = REPLACE(icongray, :old_substring, :new_substring)
                WHERE appid = :appid AND user_id = :user_id
            """)
            await db.execute(query, {
                "appid": appid,
                "old_substring": old_substring,
                "new_substring": new_substring,
                "user_id": user.id,
            })
            await db.commit()

            logger_app.info("Пути обновлены успешно")
            return {"success": True, "message": "Пути обновлены успешно"}

        except Exception as e:
            await db.rollback()
            raise HTTPException(status_code=500, detail=f"Ошибка при обновлении путей: {str(e)}")
        finally:
            logger_app.info("-" * 60)

# Получение данных об игре из стим
@router.get("/api/steam_appdetails/{appid}")
async def steam_proxy(appid: int):
    url = f"https://store.steampowered.com/api/appdetails?appids={appid}&cc=us&l=ru"
    headers = {
        "Accept-Language": "ru",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache"
    }
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)
    return JSONResponse(content=response.json())

# Поиск игры
@router.get("/api/search")
async def search_releases(q: str = Query(..., min_length=2)):
    async with SessionLocal() as session:
        stmt = (
            select(Release)
            .where(
                or_(
                    Release.name.ilike(f"%{q}%"),
                    cast(Release.appid, String).ilike(f"%{q}%")
                )
            )
            .where(Release.type == 'game')
            .limit(10)
        )
        result = await session.execute(stmt)
        releases = result.scalars().all()
        return [
            {"name": r.name, "appid": r.appid, "release_date": r.release_date}
            for r in releases
        ]

# Добавление игры в избранное
@router.post("/favorites/{appid}")
async def add_favorite(appid: int, user=Depends(manager)):
    async with SessionLocal() as session:
        stmt = select(Favorite).where(Favorite.user_id == user.id, Favorite.appid == appid)
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            raise HTTPException(status_code=400, detail="Игра уже в избранном")

        session.add(Favorite(user_id=user.id, appid=appid))
        await session.commit()
        return {"message": "Добавлено в избранное"}

# Удаление игры из избранного
@router.delete("/favorites/{appid}")
async def remove_favorite(appid: int, user=Depends(manager)):
    async with SessionLocal() as session:
        stmt = select(Favorite).where(Favorite.user_id == user.id, Favorite.appid == appid)
        result = await session.execute(stmt)
        favorite = result.scalar_one_or_none()

        if not favorite:
            raise HTTPException(status_code=404, detail="Игра не найдена в избранном")

        await session.delete(favorite)
        await session.commit()
        return {"message": "Удалено из избранного"}