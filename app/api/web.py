from fastapi import APIRouter, Request, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from datetime import datetime, timedelta
from calendar import monthrange
from sqlalchemy.future import select
from sqlalchemy import text
import traceback

from app.core.auth import manager
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.images import ensure_header_image, ensure_background_image
from app.core.games import get_games, get_user_favorites, get_releases, get_game_name, archive_game, unarchive_game, get_archived_games, get_game_slug_powerpyx, \
    youtube_search_link
from app.core.achievements import get_achievements_for_game
from app.models import Wanted, Release, Favorite, Game
from app.core.logger import logger_app

router = APIRouter()
templates = Jinja2Templates(directory="templates")


# Главная страница
@router.get("/", response_class=HTMLResponse)
async def home(request: Request, user=Depends(manager)):
    async with SessionLocal() as session:
        try:
            if not request.session.get("logged_once"):
                logger_app.info(f"авторизован юзер: {user.username, user.id}")
                request.session["logged_once"] = True

            games = await get_games(session, user.id)
            now = datetime.now()
            return templates.TemplateResponse("index.html", {"request": request, "games": games, "user": user, "now": now})
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to fetch games data: {str(e)}")


# Страница авторизации
@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


# Страница конкретного релиза
@router.get("/release/{appid}", response_class=HTMLResponse)
async def release_page(request: Request, appid: int, user=Depends(manager)):
    now = datetime.now()

    async with SessionLocal() as session:
        try:
            favorite_appids = await get_user_favorites(user.id, session)
            return templates.TemplateResponse("release.html",
                                              {"request": request, "appid": appid, "now": now, "favorite_appids": favorite_appids, "user": user})
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Ошибка при загрузке страницы релиза: {str(e)}")


# Страница календаря релизов за месяц
@router.get("/calendar/{year}/{month}", name="game_calendar")
async def game_calendar(request: Request, year: int = None, month: int = None, user=Depends(manager)):
    today = datetime.today()
    year = year or today.year
    main_year = today.year
    month = month or today.month
    month_name_rus = settings.MONTHS_MAP_RUSSIAN.get(month, "Unknown")

    async with SessionLocal() as session:
        try:
            calendar_data = await get_releases(session, year, month, user.id)
            month_name = settings.MONTHS_MAP.get(month, "Unknown")
            first_day_of_month = datetime(year, month, 1)
            days_in_month = monthrange(year, month)[1]
            now = datetime.now()
            return templates.TemplateResponse("calendar.html",
                                              {"request": request, "calendar_data": calendar_data, "user": user,
                                               "datetime": datetime,
                                               "MONTHS_MAP_REV": settings.MONTHS_MAP_REV, "current_year": year,
                                               "current_month": month_name,
                                               "month_name": month_name_rus, "main_year": main_year,
                                               "russian_months": settings.MONTHS_MAP_RUSSIAN,
                                               "current_month_int": month, "first_day_of_month": first_day_of_month,
                                               "days_in_month": days_in_month, "now": now})
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to fetch releases data: {str(e)}")


# Страница календаря релизов за конкретную дату
@router.get("/releases/{year}/{month}/{day}", name="releases_by_day")
async def releases_by_day(request: Request, year: int, month: int, day: int, user=Depends(manager)):
    try:
        async with SessionLocal() as session:
            calendar_data = await get_releases(session, year, month, user.id)
            releases = calendar_data.get(datetime(year, month, day).date(), [])
            now = datetime.now()
            return templates.TemplateResponse("releases.html", {"request": request, "user": user, "releases": releases,
                                                                "formatted_date": f"{day} {settings.MONTHS_MAP_RUSSIAN.get(month, str(month))} {year}",
                                                                "now": now})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка при получении релизов за дату: {str(e)}")


# Страница ожидаемых игр
@router.get("/wanted", response_class=HTMLResponse)
async def wanted_games(request: Request, user=Depends(manager)):
    async with SessionLocal() as session:
        try:
            result = await session.execute(select(Wanted).where(Wanted.appid.is_not(None)).order_by(Wanted.added.desc()))
            wanted_list = result.scalars().all()

            return templates.TemplateResponse("wanted.html", {"request": request, "user": user, "wanted": wanted_list, "now": datetime.now()})
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Ошибка загрузки: {str(e)}")


# Страница последних обновлений
@router.get("/last_releases", response_class=HTMLResponse)
async def last_releases(request: Request, user=Depends(manager)):
    async with SessionLocal() as session:
        try:
            genre_filters = " OR ".join([f"',' || genres || ',' LIKE '%,{g},%'" for g in settings.EXCLUDED_GENRES])
            sql = text(
                f"""SELECT * FROM releases WHERE DATE(updated_at) >= DATE('now', '-2 days') AND type = 'game' AND NOT ({genre_filters}) ORDER BY updated_at DESC""")
            result = await session.execute(sql)
            raw_games = result.mappings().all()

            games = []
            for game in raw_games:
                game = dict(game)
                game['updated_at'] = datetime.fromisoformat(game['updated_at']) + timedelta(hours=3)  # смещение на МСК
                games.append(game)

            now = datetime.now()
            return templates.TemplateResponse("last_releases.html", {"request": request, "user": user, "releases": games, "now": now, })
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Ошибка загрузки: {str(e)}")


# Страница избранных игр
@router.get("/favorites", response_class=HTMLResponse)
async def show_favorites(request: Request, user=Depends(manager)):
    async with SessionLocal() as session:
        try:
            stmt = (select(Release).join(Favorite, Favorite.appid == Release.appid).where(Favorite.user_id == user.id))
            result = await session.execute(stmt)
            releases = result.scalars().all()
            now = datetime.now()

            return templates.TemplateResponse("favorites.html", {"request": request, "releases": releases, "user": user, "now": now})
        except Exception as e:
            import traceback
            raise HTTPException(status_code=500, detail=f"Не удалось загрузить избранное:  {str(e)}")


# Страница ссылок игры на трекерах
@router.get("/trackers/{appid}", response_class=HTMLResponse)
async def trackers(request: Request, appid: int, user=Depends(manager)):
    async with SessionLocal() as session:
        try:
            game_name = await get_game_name(session, appid, user.id)
            background_url = f"/static/images/background/{appid}.jpg"
            now = datetime.now()
            return templates.TemplateResponse("trackers.html",
                                              {"request": request, "appid": appid, "game_name": game_name, "background": background_url, "now": now}, )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to fetch games data: {str(e)}")


# Страница достижений выбранной игры
@router.get("/achievements/{appid}", response_class=HTMLResponse)
async def achievements(request: Request, appid: int, user=Depends(manager)):
    async with SessionLocal() as session:
        try:
            achievements = await get_achievements_for_game(session, appid, user.id)
            game_name = await get_game_name(session, appid, user.id)
            game_slug = await get_game_slug_powerpyx(game_name.name)
            youtube_link = await youtube_search_link(game_name.name)
            background_url = f"/static/images/background/{appid}.jpg"
            now = datetime.now()
            achievements_data = [
                {"name": achievement.displayname, "icon": achievement.icon, "earned": achievement.earned, "link": achievement.icongray,
                 "earned_date": achievement.obtained_date, "yt_ach": await youtube_search_link(f"{game_name.name} {achievement.displayname}")}
                for achievement in achievements
            ]

            return templates.TemplateResponse("achievements.html",
                                              {"request": request, "appid": appid, "achievements": achievements_data, "game_name": game_name,
                                               "game_slug": game_slug, "youtube": youtube_link,
                                               "background": background_url, "now": now}, )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to fetch games data: {str(e)}")


# Архивирование игры
@router.post("/archive/{appid}")
async def archive_game_endpoint(appid: int, request: Request, user=Depends(manager)):
    async with SessionLocal() as session:
        await archive_game(session, user.id, appid)
        return JSONResponse({"status": "archived", "appid": appid}, status_code=status.HTTP_200_OK)


# Возврат игры из архива
@router.post("/unarchive/{appid}")
async def unarchive_game_endpoint(appid: int, request: Request, user=Depends(manager)):
    async with SessionLocal() as session:
        await unarchive_game(session, user.id, appid)
        return JSONResponse({"status": "unarchived", "appid": appid}, status_code=status.HTTP_200_OK)


# Страница архива
@router.get("/archived")
async def get_archived_games_endpoint(request: Request, user=Depends(manager)):
    async with SessionLocal() as session:
        games = await get_archived_games(session, user.id)

        result = []
        for archived_game in games:
            stmt = await session.execute(select(Game).where(Game.appid == archived_game.appid, Game.user_id == user.id))
            game = stmt.scalar_one_or_none()
            if game:
                game.background = await ensure_header_image(session, game.appid)
                await ensure_background_image(session, game.appid)
                result.append({
                    "appid": game.appid,
                    "name": game.name,
                    "background": game.background
                })
            else:
                result.append({
                    "appid": archived_game.appid,
                    "name": f"Игра {archived_game.appid}",
                    "background": f"/static/images/background/{archived_game.appid}.jpg"
                })

        return JSONResponse(result, status_code=status.HTTP_200_OK)
