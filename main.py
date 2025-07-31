import asyncio
import functools
import hashlib
import hmac
import httpx
import json
import logging
import os
import requests
import sqlite3
import time
import uvicorn
import websockets

from calendar import monthrange
from collections import defaultdict
from crud import get_games, get_achievements_for_game, get_game_name, parse_release_date, get_releases
from database import init_db, SessionLocal, SyncSessionLocal
from datetime import datetime, timedelta
from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException, Request, BackgroundTasks, Query, Form, Path
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi_login import LoginManager
from fastapi_login.exceptions import InvalidCredentialsException
from models import Achievement, Game, PushSubscription, PushSubscriptionCreate, User, Release, Favorite, Wanted
from passlib.context import CryptContext
from pydantic import BaseModel
from pywebpush import webpush, WebPushException
from sqlalchemy import text, or_, cast, String
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse
from steam_api import fetch_game_data, get_achievement_url
from tasks.check_favorites import start_scheduler
from typing import Dict

if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True, )

load_dotenv()
app = FastAPI()

# SETTINGS
SECRET_KEY = os.getenv("SECRET_KEY")
app.add_middleware(SessionMiddleware, SECRET_KEY)
BOT_TOKEN = os.getenv("BOT_TOKEN")
ALLOWED_USER_ID = int(os.getenv("ALLOWED_USER_ID"))

telegram_ids_raw = os.getenv("TELEGRAM_IDS", "")
telegram_ids = [int(tid.strip()) for tid in telegram_ids_raw.split(",") if tid.strip()]
user_ids = [1, 2]
user_to_telegram = dict(zip(user_ids, telegram_ids))

manager = LoginManager(SECRET_KEY, token_url='/login', use_cookie=True)
manager.cookie_name = "auth_token"
manager.lifetime_seconds = 31536000
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

logging.basicConfig(filename="app.log", level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", )
logging.getLogger("apscheduler").propagate = False
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/.well-known", StaticFiles(directory="./.well-known"), name=".well-known")

MONTHS_MAP = {
    1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
    7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec"
}
MONTHS_MAP_RUSSIAN = {
    1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель", 5: "Май", 6: "Июнь",
    7: "Июль", 8: "Август", 9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь"
}
MONTHS_MAP_REV = {v: k for k, v in MONTHS_MAP.items()}

EXCLUDED_GENRES = {"4", "23", "57", "55", "51"}

VAPID_PRIVATE_KEY_PATH = os.getenv("VAPID_PRIVATE_KEY_PATH")
VAPID_CLAIMS = {"sub": os.getenv("VAPID_CLAIMS")}


# MODELS
class SubscriptionCheckRequest(BaseModel):
    endpoint: str


class AchievementData(BaseModel):
    appid: int
    achievement_name: str
    obtained_time: int
    user_id: int


class TestPushNotification(BaseModel):
    title: str
    body: str
    icon: str
    url: str


# APPLICATION
@app.on_event("startup")
async def startup():
    await init_db()
    start_scheduler()
    asyncio.create_task(websocket_listener())


# HELPERS
@manager.user_loader()
async def load_user(username: str):
    async with SessionLocal() as session:
        result = await session.execute(select(User).where(User.username == username))
        return result.scalar_one_or_none()


@app.middleware("http")
async def redirect_unauthed(request: Request, call_next):
    if request.url.path == "/" and not request.cookies.get(manager.cookie_name):
        return RedirectResponse(url="/login")
    response = await call_next(request)
    return response


def parse_date_str(date_str):
    try:
        return datetime.fromisoformat(date_str)
    except Exception:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(date_str, fmt)
            except Exception:
                continue
    return date_str


async def send_push_notification_async(subscription, title, body, icon, url):
    loop = asyncio.get_event_loop()
    max_retries = 3
    delay_seconds = 5

    for attempt in range(max_retries):
        try:
            await loop.run_in_executor(
                None,
                functools.partial(
                    webpush,
                    subscription_info={"endpoint": subscription.endpoint, "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth, }, },
                    data=json.dumps({"title": title, "body": body, "icon": icon, "url": url, }),
                    vapid_private_key=VAPID_PRIVATE_KEY_PATH,
                    vapid_claims=VAPID_CLAIMS,
                    timeout=30
                )
            )
            logging.info(f"Push отправлен: {title}")
            break

        except WebPushException as ex:
            logging.error(f"Ошибка отправки push: {repr(ex)}")

            if "404" in str(ex) or "410" in str(ex):
                async with SessionLocal() as db:
                    sub_db = await db.execute(select(PushSubscription).where(PushSubscription.endpoint == subscription.endpoint))
                    sub_obj = sub_db.scalar_one_or_none()
                    if sub_obj:
                        await db.delete(sub_obj)
                        await db.commit()
                        logging.info(f"Удалена подписка с endpoint {subscription.endpoint}")
                break

            else:
                logging.info(f"Попытка {attempt + 1} из {max_retries} не удалась, повтор через {delay_seconds} сек")
                await asyncio.sleep(delay_seconds)

        except Exception as e:
            logging.error(f"Неожиданная ошибка при отправке push: {e}")
            logging.info(f"Попытка {attempt + 1} из {max_retries} не удалась, повтор через {delay_seconds} сек")
            await asyncio.sleep(delay_seconds)

    else:
        logging.error(f"Не удалось отправить push после {max_retries} попыток")


async def get_user_favorites(user_id: int, session: AsyncSession) -> list[int]:
    query = select(Favorite.appid).where(Favorite.user_id == user_id)
    result = await session.execute(query)
    return [row[0] for row in result.fetchall()]


async def update_achievement(session: AsyncSession, appid: int, achievement_name: str, obtained_time: int, user_id: int, ):
    obtained_date = datetime.utcfromtimestamp(obtained_time)

    query = select(Achievement).where(Achievement.appid == appid, Achievement.name == achievement_name, Achievement.user_id == user_id)
    result = await session.execute(query)
    achievement = result.scalar_one_or_none()

    if achievement:
        achievement.obtained_date = obtained_date
        await session.commit()
        logging.info(f"Обновлено достижение {achievement_name}")

        title = achievement.displayname
        body = f"Вы получили достижение: {achievement_name}!"
        icon = achievement.icon
        url = achievement.icongray

        async with SessionLocal() as db:
            subscriptions_result = await db.execute(select(PushSubscription).where(PushSubscription.user_id == user_id))
            subscriptions = subscriptions_result.scalars().all()

            for sub in subscriptions:
                await send_push_notification_async(sub, title, body, icon, url)

        result = await session.execute(select(Game).filter(Game.appid == appid).filter(Game.user_id == user_id))
        game = result.scalars().first()

        if game is None:
            logging.error("Игра не найдена")
            return {"error": "Игра не найдена"}

        game_name = game.name
        message = f"Ачивка в игре {game_name}: {title}\nСсылка: {url}"

        for tg_user_id, telegram_id in user_to_telegram.items():
            if user_id == tg_user_id:
                send_telegram_message_with_image(telegram_id, message, BOT_TOKEN, icon)
                logging.info(f"Отправили уведомление в телеграм {title}")


async def websocket_listener():
    uri = "ws://192.168.1.111:8082"
    user_id = 1
    while True:
        try:
            async with websockets.connect(uri) as websocket:
                async for message in websocket:
                    data = json.loads(message)
                    async with SessionLocal() as session:
                        obtained_time = int(data["time"]) + 3 * 3600

                        asyncio.create_task(update_achievement(session, int(data["appID"]), data["achievement"], obtained_time, user_id))
                        logging.info("Отправили ачивку с локального вебсокета")
        except Exception as e:
            await asyncio.sleep(5)


def send_telegram_message_with_image(chat_id: int, message: str, bot_token: str, image_url: str):
    url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
    payload = {"chat_id": chat_id, "caption": message, "parse_mode": "HTML", "photo": image_url}
    try:
        response = requests.post(url, data=payload, timeout=15)
        response.raise_for_status()
        logging.info(f"Сообщение успешно отправлено в Telegram: {response.status_code}")
        return response
    except requests.exceptions.Timeout:
        logging.error("Timeout при отправке сообщения в Telegram")
    except requests.exceptions.RequestException as e:
        logging.error(f"Ошибка при отправке сообщения в Telegram: {e}")
    return None


# ENDPOINTS
@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.get("/log/{log_name}", response_class=PlainTextResponse)
async def get_log(log_name: str = Path(..., pattern="^(app|releases|updater)$")):
    filename = f"{log_name}.log"
    log_path = os.path.join(os.getcwd(), filename)
    if os.path.exists(log_path):
        with open(log_path, "r", encoding="utf-8") as f:
            return f.read()
    return f"Файл {filename} не найден."


@app.get("/api/steam_appdetails/{appid}")
async def steam_proxy(appid: int):
    url = f"https://store.steampowered.com/api/appdetails?appids={appid}&cc=us&l=ru"
    headers = {"Accept-Language": "ru", "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Cache-Control": "no-cache", "Pragma": "no-cache"}
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)
    return JSONResponse(content=response.json())


@app.get("/release/{appid}", response_class=HTMLResponse)
async def release_page(request: Request, appid: int, user=Depends(manager)):
    now = datetime.now()

    async with SessionLocal() as session:
        try:
            favorite_appids = await get_user_favorites(user.id, session)
            return templates.TemplateResponse("release.html",
                                              {"request": request, "appid": appid, "now": now, "favorite_appids": favorite_appids, "user": user})
        except Exception as e:
            raise HTTPException(status_code=500, detail="Ошибка при загрузке страницы релиза")


@app.get("/calendar/{year}/{month}", name="game_calendar")
async def game_calendar(request: Request, year: int = None, month: int = None, user=Depends(manager)):
    today = datetime.today()
    year = year or today.year
    main_year = today.year
    month = month or today.month
    month_name = MONTHS_MAP.get(month, "Unknown")
    month_name_rus = MONTHS_MAP_RUSSIAN.get(month, "Unknown")

    async with SessionLocal() as session:
        try:
            calendar_data = await get_releases(session, year, month, user.id)
            month_name = MONTHS_MAP.get(month, "Unknown")
            first_day_of_month = datetime(year, month, 1)
            days_in_month = monthrange(year, month)[1]
            now = datetime.now()
            return templates.TemplateResponse("calendar.html", {"request": request, "calendar_data": calendar_data, "user": user, "datetime": datetime,
                                                                "MONTHS_MAP_REV": MONTHS_MAP_REV, "current_year": year, "current_month": month_name,
                                                                "month_name": month_name_rus, "main_year": main_year, "russian_months": MONTHS_MAP_RUSSIAN,
                                                                "current_month_int": month, "first_day_of_month": first_day_of_month,
                                                                "days_in_month": days_in_month, "now": now})
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to fetch releases data: {str(e)}")


@app.get("/releases/{year}/{month}/{day}", name="releases_by_day")
async def releases_by_day(request: Request, year: int, month: int, day: int, user=Depends(manager)):
    try:
        date_str = f"{day:02}.{month:02}.{year}"
        async with SessionLocal() as session:
            calendar_data = await get_releases(session, year, month, user.id)
            target_date = f"{year:04}-{month:02}-{day:02}"
            releases = calendar_data.get(datetime(year, month, day).date(), [])
            now = datetime.now()
            return templates.TemplateResponse("releases.html", {"request": request, "user": user, "releases": releases,
                                                                "formatted_date": f"{day} {MONTHS_MAP_RUSSIAN.get(month, str(month))} {year}", "now": now})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка при получении релизов за дату: {str(e)}")


@app.get("/wanted", response_class=HTMLResponse)
async def wanted_games(request: Request, user=Depends(manager)):
    async with SessionLocal() as session:
        try:
            result = await session.execute(select(Wanted).where(Wanted.appid.is_not(None)).order_by(Wanted.added.desc()))
            wanted_list = result.scalars().all()

            return templates.TemplateResponse("wanted.html", {"request": request, "user": user, "wanted": wanted_list, "now": datetime.now()})
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Ошибка загрузки: {str(e)}")


@app.get("/last_releases", response_class=HTMLResponse)
async def last_releases(request: Request, user=Depends(manager)):
    async with SessionLocal() as session:
        try:
            genre_filters = " OR ".join([f"',' || genres || ',' LIKE '%,{g},%'" for g in EXCLUDED_GENRES])
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


@app.get("/", response_class=HTMLResponse)
async def home(request: Request, user=Depends(manager)):
    async with SessionLocal() as session:
        try:
            session_flag = request.session.get("logged_once", False)
            if not session_flag:
                logging.info(f"авторизован юзер: {user.username, user.id}")
                request.session["logged_once"] = True
            games = await get_games(session, user.id)
            now = datetime.now()
            return templates.TemplateResponse("index.html", {"request": request, "games": games, "user": user, "now": now})
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to fetch games data: {str(e)}")


@app.get("/favorites", response_class=HTMLResponse)
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
            raise HTTPException(status_code=500, detail="Не удалось загрузить избранное")


@app.get("/trackers/{appid}", response_class=HTMLResponse)
async def trackers(request: Request, appid: int, user=Depends(manager)):
    async with SessionLocal() as session:
        try:
            game_name = await get_game_name(session, appid, user.id)
            background_url = f"/static/images/background/{appid}.jpg"
            now = datetime.now()
            return templates.TemplateResponse("trackers.html",
                                              {"request": request, "appid": appid, "game_name": game_name, "background": background_url, "now": now}, )
        except Exception as e:
            return {"error": "Failed to fetch games data"}


@app.get("/achievements/{appid}", response_class=HTMLResponse)
async def achievements(request: Request, appid: int, user=Depends(manager)):
    async with SessionLocal() as session:
        try:
            achievements = await get_achievements_for_game(session, appid, user.id)
            game_name = await get_game_name(session, appid, user.id)
            background_url = f"/static/images/background/{appid}.jpg"
            now = datetime.now()
            achievements_data = [
                {"name": achievement.displayname, "icon": achievement.icon, "earned": achievement.earned, "link": achievement.icongray,
                 "earned_date": achievement.obtained_date, }
                for achievement in achievements
            ]

            return templates.TemplateResponse("achievements.html",
                                              {"request": request, "appid": appid, "achievements": achievements_data, "game_name": game_name,
                                               "background": background_url, "now": now}, )
        except Exception as e:
            return {"error": "Failed to fetch games data"}


@app.get("/api/search")
async def search_releases(q: str = Query(..., min_length=2)):
    async with SessionLocal() as session:
        stmt = (select(Release).where(or_(Release.name.ilike(f"%{q}%"), cast(Release.appid, String).ilike(f"%{q}%"))).where(Release.type == 'game').limit(10))
        result = await session.execute(stmt)
        releases = result.scalars().all()
        return [
            {"name": r.name, "appid": r.appid, "release_date": r.release_date}
            for r in releases
        ]


@app.get("/send_test_notification")
async def send_test_notification():
    achiev_name = "softUnderbelly"

    async with SessionLocal() as db:
        result = await db.execute(select(Achievement).where(Achievement.name == achiev_name).where(Achievement.user_id == 1))
        achievement = result.scalars().first()

        if achievement is None:
            return {"error": "Достижение не найдено"}

        appid = achievement.appid

        result = await db.execute(select(Game).filter(Game.appid == appid).filter(Game.user_id == 1))
        game = result.scalars().first()

        if game is None:
            return {"error": "Игра не найдена"}

        game_name = game.name

        title = achievement.displayname
        body = f"Вы получили достижение: {title}"
        icon = achievement.icon
        url = achievement.icongray

        message = f"Ачивка в игре {game_name}: {title}\nСсылка: {url}"

        subscriptions_result = await db.execute(select(PushSubscription))
        subscriptions = subscriptions_result.scalars().all()

        for sub in subscriptions:
            await send_push_notification_async(sub, title, body, icon, url)

        for user_id, telegram_id in user_to_telegram.items():
            send_telegram_message_with_image(telegram_id, message, BOT_TOKEN, icon)

    return {"message": "Тестовое уведомление отправлено"}


# BACKEND
@app.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    user = await load_user(username)
    if not user or not pwd_context.verify(password, user.hashed_password):
        raise InvalidCredentialsException
    token = manager.create_access_token(data={"sub": username}, expires=timedelta(days=365))
    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie(key=manager.cookie_name, value=token, httponly=True, max_age=31536000, samesite="lax", secure=False)
    return response


@app.post("/check_subscription")
async def check_subscription(data: SubscriptionCheckRequest, user=Depends(manager)):
    async with SessionLocal() as db:
        result = await db.execute(select(PushSubscription).where(PushSubscription.endpoint == data.endpoint, PushSubscription.user_id == user.id))
        sub = result.scalar_one_or_none()
        return {"exists": sub is not None}


@app.post("/subscribe")
async def subscribe(subscription: PushSubscriptionCreate, user=Depends(manager)):
    async with SessionLocal() as db:
        new_sub = PushSubscription(endpoint=subscription.endpoint, p256dh=subscription.p256dh, auth=subscription.auth, user_id=user.id)
        db.add(new_sub)
        try:
            await db.commit()
            return {"message": "Подписка сохранена"}
        except Exception as e:
            await db.rollback()
            raise HTTPException(status_code=500, detail=f"Ошибка: {e}")


@app.post("/favorites/{appid}")
async def add_favorite(appid: int, user=Depends(manager)):
    async with SessionLocal() as session:
        try:
            stmt = select(Favorite).where(Favorite.user_id == user.id, Favorite.appid == appid)
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()

            if existing:
                raise HTTPException(status_code=400, detail="Игра уже в избранном")

            session.add(Favorite(user_id=user.id, appid=appid))
            await session.commit()
            return {"message": "Добавлено в избранное"}
        except Exception as e:
            raise HTTPException(status_code=500, detail="Ошибка сервера")


@app.delete("/favorites/{appid}")
async def remove_favorite(appid: int, user=Depends(manager)):
    async with SessionLocal() as session:
        try:
            stmt = select(Favorite).where(Favorite.user_id == user.id, Favorite.appid == appid)
            result = await session.execute(stmt)
            favorite = result.scalar_one_or_none()

            if not favorite:
                raise HTTPException(status_code=404, detail="Игра не найдена в избранном")

            await session.delete(favorite)
            await session.commit()
            return {"message": "Удалено из избранного"}
        except Exception as e:
            raise HTTPException(status_code=500, detail="Ошибка сервера")


@app.post("/api/update_achievement")
async def update_achievement_endpoint(data: AchievementData):
    async with SessionLocal() as session:
        await update_achievement(session=session, appid=data.appid, achievement_name=data.achievement_name, obtained_time=data.obtained_time,
                                 user_id=data.user_id)
        logging.info(f"Отправили ачивку с удаленного вебсокета, {data.achievement_name}")
        return {"message": "Achievement updated successfully"}


@app.post("/add_game")
async def add_game(request: Request, user=Depends(manager)):
    async with SessionLocal() as db:
        data = await request.json()
        logging.info(f"Получены данные игры: {data}")

        try:
            appid = int(data["appid"])
        except (KeyError, ValueError):
            raise HTTPException(status_code=400, detail="Некорректный формат appid")

        logging.info(f"Спарсили appid: {appid}")

        existing_game = await db.execute(select(Game).filter(Game.appid == appid).filter(Game.user_id == user.id))
        if existing_game.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Игра уже добавлена")

        game_data = await fetch_game_data(appid)
        if not game_data or "game" not in game_data:
            raise HTTPException(status_code=404, detail="Игра не найдена в Steam")

        game_name = game_data["game"]["gameName"]

        new_game = Game(appid=appid, name=game_name, user_id=user.id)
        db.add(new_game)

        achievements = (game_data["game"].get("availableGameStats", {}).get("achievements", []))
        for ach in achievements:
            icongray_url = await get_achievement_url(game_name, ach["displayName"])

            achievement = Achievement(appid=appid, name=ach["name"], displayname=ach["displayName"], defaultval=ach.get("defaultValue", 0),
                                      hidden=ach.get("hidden", 0), icon=ach.get("icon", ""), icongray=icongray_url, obtained_date=None, user_id=user.id)
            db.add(achievement)

        try:
            await db.commit()
            logging.info("Игра и достижения добавлены")
            return {"message": "Игра и достижения добавлены"}
        except IntegrityError:
            await db.rollback()
            raise HTTPException(status_code=500, detail="Ошибка при добавлении игры")


@app.post("/update_paths")
async def update_paths(request: Request, user=Depends(manager)):
    async with SessionLocal() as db:
        data = await request.json()
        logging.info(f"Получили данные по игре: {data}")

        appid = data.get("appid")
        old_substring = data.get("oldSubstring")
        new_substring = data.get("newSubstring")

        if not all([appid, old_substring, new_substring]):
            raise HTTPException(status_code=400, detail="Все поля должны быть заполнены")

        try:
            appid = int(appid)
        except ValueError:
            raise HTTPException(status_code=400, detail="Некорректный формат appid")

        logging.info(f"Спарсили успешно: {appid}")

        try:
            query = text(
                """
                UPDATE achievements
                SET icongray = REPLACE(icongray, :old_substring, :new_substring)
                WHERE appid = :appid AND user_id = :user_id
            """)
            await db.execute(query, {"appid": appid, "old_substring": old_substring, "new_substring": new_substring, "user_id": user.id, }, )
            await db.commit()

            logging.info("Пути обновлены успешно")
            return {"success": True, "message": "Пути обновлены успешно"}

        except Exception as e:
            await db.rollback()
            raise HTTPException(status_code=500, detail=f"Ошибка при обновлении путей: {str(e)}", )
