import asyncio
import httpx
import json
import websockets
from datetime import datetime
from pydantic import BaseModel
from steam_api import fetch_game_data, get_achievement_url
from fastapi import FastAPI, Depends, HTTPException, Request, BackgroundTasks, Query, Form
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse
from database import init_db, SessionLocal, SyncSessionLocal
from crud import get_games, get_achievements_for_game, get_game_name, parse_release_date, get_releases
from models import Achievement, Game, PushSubscription, PushSubscriptionCreate, User, Release, Favorite
from sqlalchemy.future import select
from sqlalchemy import or_, cast, String
from sqlalchemy.exc import IntegrityError
import uvicorn
import hashlib
import hmac
import time
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
import logging
import sqlite3
from typing import Dict
import requests
from pywebpush import webpush, WebPushException
import os
from dotenv import load_dotenv
from fastapi_login import LoginManager
from fastapi_login.exceptions import InvalidCredentialsException
from passlib.context import CryptContext
from datetime import timedelta
from collections import defaultdict
from calendar import monthrange

if __name__ == "__main__":
    uvicorn.run(
        "main:app",  # укажите путь к вашему приложению
        host="127.0.0.1",
        port=8000,
        reload=True,  # включить перезагрузку при изменении кода
    )

# Загрузка переменных из .env
load_dotenv()

app = FastAPI()

SECRET_KEY = os.getenv("SECRET_KEY")
# 🔑 Добавляем поддержку сессий (ключ должен быть секретным!)
app.add_middleware(SessionMiddleware, SECRET_KEY)
BOT_TOKEN = os.getenv("BOT_TOKEN")
ALLOWED_USER_ID = int(os.getenv("ALLOWED_USER_ID"))

telegram_ids_raw = os.getenv("TELEGRAM_IDS", "")
telegram_ids = [int(tid.strip()) for tid in telegram_ids_raw.split(",") if tid.strip()]

user_ids = [1, 2]
user_to_telegram = dict(zip(user_ids, telegram_ids))

manager = LoginManager(SECRET_KEY, token_url='/login', use_cookie=True)
manager.cookie_name = "auth_token"
manager.lifetime_seconds = 31536000  # 7 дней = 60 * 60 * 24 * 7

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Настройка логирования
logging.basicConfig(
    filename="app.log",  # Имя файла для записи логов
    level=logging.INFO,  # Уровень логирования
    format="%(asctime)s - %(levelname)s - %(message)s",  # Формат сообщений
)


@manager.user_loader()
async def load_user(username: str):
    async with SessionLocal() as session:
        result = await session.execute(select(User).where(User.username == username))
        return result.scalar_one_or_none()


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    user = await load_user(username)
    if not user or not pwd_context.verify(password, user.hashed_password):
        raise InvalidCredentialsException
    token = manager.create_access_token(data={"sub": username}, expires=timedelta(days=365))
    response = RedirectResponse(url="/", status_code=302)
    # manager.set_cookie(response, token)
    response.set_cookie(
        key=manager.cookie_name,
        value=token,
        httponly=True,
        max_age=31536000,  # 1 год
        samesite="lax",  # или strict/none в зависимости от нужд
        secure=False  # True, если используешь HTTPS
    )
    return response

class SubscriptionCheckRequest(BaseModel):
    endpoint: str

@app.post("/check_subscription")
async def check_subscription(data: SubscriptionCheckRequest, user=Depends(manager)):
    async with SessionLocal() as db:
        result = await db.execute(
            select(PushSubscription).where(
                PushSubscription.endpoint == data.endpoint,
                PushSubscription.user_id == user.id
            )
        )
        sub = result.scalar_one_or_none()
        return {"exists": sub is not None}

@app.post("/subscribe")
async def subscribe(subscription: PushSubscriptionCreate, user=Depends(manager)):
    async with SessionLocal() as db:
        new_sub = PushSubscription(
            endpoint=subscription.endpoint,
            p256dh=subscription.p256dh,
            auth=subscription.auth,
            user_id=user.id  # Привязка к авторизованному пользователю
        )
        db.add(new_sub)
        try:
            await db.commit()
            logging.info(f"Подписка сохранена для user_id={user.id}")
            return {"message": "Подписка сохранена"}
        except Exception as e:
            await db.rollback()
            logging.error(f"Ошибка: {e}")
            raise HTTPException(status_code=500, detail=f"Ошибка: {e}")


@app.middleware("http")
async def redirect_unauthed(request: Request, call_next):
    if request.url.path == "/" and not request.cookies.get(manager.cookie_name):
        return RedirectResponse(url="/login")
    response = await call_next(request)
    return response


# Подключение шаблонов Jinja2
templates = Jinja2Templates(directory="templates")

# Статические файлы (для изображений и стилей)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.on_event("startup")
async def startup():
    # Инициализация базы данных при старте приложения
    await init_db()
    # Запуск фонового веб-сокет обработчика
    asyncio.create_task(websocket_listener())

@app.get("/api/steam_appdetails/{appid}")
async def steam_proxy(appid: int):
    url = f"https://store.steampowered.com/api/appdetails?appids={appid}&cc=us&l=ru"
    headers = {
        "Accept-Language": "ru",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)
    return JSONResponse(content=response.json())

@app.get("/release/{appid}", response_class=HTMLResponse)
async def release_page(request: Request, appid: int, user=Depends(manager)):
    now = datetime.now()

    async with SessionLocal() as session:
        try:
            favorite_appids = await get_user_favorites(user.id, session)
            return templates.TemplateResponse("release.html", {
                "request": request,
                "appid": appid,
                "now": now,
                "favorite_appids": favorite_appids,
                "user": user
            })
        except Exception as e:
            logging.error(f"Ошибка загрузки страницы релиза для appid={appid}: {str(e)}")
            raise HTTPException(status_code=500, detail="Ошибка при загрузке страницы релиза")

MONTHS_MAP = {
    1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
    7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec"
}

MONTHS_MAP_RUSSIAN = {
    1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель", 5: "Май", 6: "Июнь",
    7: "Июль", 8: "Август", 9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь"
}

MONTHS_MAP_REV = {v: k for k, v in MONTHS_MAP.items()}

@app.get("/calendar/{year}/{month}", name="game_calendar")
async def game_calendar(request: Request, year: int = None, month: int = None, user=Depends(manager)):
    logging.info(f"Отдаем релизы юзеру: {user.username, user.id}")
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
            return templates.TemplateResponse("calendar.html", {
                "request": request,
                "calendar_data": calendar_data,  # передаем именно calendar_data
                "user": user,
                "datetime": datetime,
                "MONTHS_MAP_REV": MONTHS_MAP_REV,
                "current_year": year,
                "current_month": month_name,
                "month_name": month_name_rus,
                "main_year": main_year,
                "russian_months": MONTHS_MAP_RUSSIAN,
                "current_month_int": month,
                "first_day_of_month": first_day_of_month,
                "days_in_month": days_in_month,
                "now": now
            })
            logging.error(f"Массив релизов {calendar_data}")
        except Exception as e:
            logging.error(f"Ошибка выборки релизов для календаря: {str(e)}")
            print(f"An error occurred while fetching games: {str(e)}")
            raise HTTPException(
                status_code=500, detail=f"Failed to fetch releases data: {str(e)}"
            )

#Страница релизов по дням
@app.get("/releases/{year}/{month}/{day}", name="releases_by_day")
async def releases_by_day(request: Request, year: int, month: int, day: int, user=Depends(manager)):
    logging.info(f"Отдаем релизы за дату: {day}-{month}-{year} для пользователя {user.username, user.id}")

    try:
        date_str = f"{day:02}.{month:02}.{year}"
        async with SessionLocal() as session:
            calendar_data = await get_releases(session, year, month, user.id)
            target_date = f"{year:04}-{month:02}-{day:02}"

            # Фильтруем релизы по точно совпадающей дате
            releases = calendar_data.get(datetime(year, month, day).date(), [])
            now = datetime.now()
            return templates.TemplateResponse("releases.html", {
                "request": request,
                "user": user,
                "releases": releases,
                "formatted_date": f"{day} {MONTHS_MAP_RUSSIAN.get(month, str(month))} {year}",
                "now": now
            })
    except Exception as e:
        logging.error(f"Ошибка выборки релизов за день: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Ошибка при получении релизов за дату: {str(e)}"
        )

# Главная страница с выводом списка игр
@app.get("/", response_class=HTMLResponse)
async def home(request: Request, user=Depends(manager)):
    logging.info(f"авторизован юзер: {user.username, user.id}")
    # Открываем сессию с базой данных
    async with SessionLocal() as session:
        try:
            # Получаем список игр из базы данных
            games = await get_games(
                session, user.id
            )  # предполагаем, что get_games возвращает список игр
            logging.info(f"Загружена главная страница для {user.username}")
            now = datetime.now()
            return templates.TemplateResponse(
                "index.html", {"request": request, "games": games, "user": user, "now": now}
            )
        except Exception as e:
            logging.error(f"Ошибка выборки игр главной страницы: {str(e)}")
            print(f"An error occurred while fetching games: {str(e)}")
            raise HTTPException(
                status_code=500, detail=f"Failed to fetch games data: {str(e)}"
            )

@app.post("/favorites/{appid}")
async def add_favorite(appid: int, user=Depends(manager)):
    async with SessionLocal() as session:
        try:
            # Проверка, есть ли уже такая запись
            stmt = select(Favorite).where(Favorite.user_id == user.id, Favorite.appid == appid)
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()

            if existing:
                raise HTTPException(status_code=400, detail="Игра уже в избранном")

            session.add(Favorite(user_id=user.id, appid=appid))
            await session.commit()
            return {"message": "Добавлено в избранное"}
        except Exception as e:
            logging.error(f"Ошибка при добавлении в избранное: {e}")
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
            logging.error(f"Ошибка при удалении из избранного: {e}")
            raise HTTPException(status_code=500, detail="Ошибка сервера")


@app.get("/favorites", response_class=HTMLResponse)
async def show_favorites(request: Request, user=Depends(manager)):
    async with SessionLocal() as session:
        try:
            stmt = (
                select(Release)
                .join(Favorite, Favorite.appid == Release.appid)
                .where(Favorite.user_id == user.id)
                # .order_by(Release.release_date)  # закомментировано для теста
            )
            #print(str(stmt.compile(compile_kwargs={"literal_binds": True})))  # Для отладки SQL
            result = await session.execute(stmt)
            releases = result.scalars().all()
            now = datetime.now()

            return templates.TemplateResponse(
                "favorites.html",
                {"request": request, "releases": releases, "user": user, "now": now}
            )
        except Exception as e:
            import traceback
            logging.error(f"Ошибка при загрузке избранного: {e}")
            logging.error(traceback.format_exc())
            raise HTTPException(status_code=500, detail="Не удалось загрузить избранное")


# Страница с раздачами
@app.get("/trackers/{appid}", response_class=HTMLResponse)
async def trackers(request: Request, appid: int, user=Depends(manager)):
    async with SessionLocal() as session:
        try:
            game_name = await get_game_name(session, appid, user.id)
            background_url = f"/static/images/background/{appid}.jpg"
            logging.info(f"Формируем страницу раздач игры {game_name.name }")
            now = datetime.now()
            return templates.TemplateResponse(
                "trackers.html",
                {
                    "request": request,
                    "appid": appid,
                    "game_name": game_name,
                    "background": background_url,
                    "now": now
                },
            )
        except Exception as e:
            logging.error(f"Ошибка формирования страницы раздач: {str(e)}")
            print(f"An error occurred while fetching games: {str(e)}")
            return {"error": "Failed to fetch games data"}


# Страница достижений
@app.get("/achievements/{appid}", response_class=HTMLResponse)
async def achievements(request: Request, appid: int, user=Depends(manager)):
    # Получаем данные о достижениях из базы данных
    # Проверяем, авторизован ли пользователь
    # user_id = request.session.get("user_id")
    # if user_id != ALLOWED_USER_ID:
    #     return RedirectResponse(url="/")
    async with SessionLocal() as session:
        try:
            achievements = await get_achievements_for_game(session, appid, user.id)
            game_name = await get_game_name(session, appid, user.id)
            background_url = f"/static/images/background/{appid}.jpg"
            now = datetime.now()
            # Подготовка данных для отображения
            achievements_data = [
                {
                    "name": achievement.displayname,
                    "icon": achievement.icon,
                    "earned": achievement.earned,  # Используем свойство earned
                    "link": achievement.icongray,
                    "earned_date": achievement.obtained_date,
                }  # Если достижение получено, то будет отображена дата
                for achievement in achievements
            ]

            logging.info(f"Загружена страница ачивок игры {game_name.name }")
            return templates.TemplateResponse(
                "achievements.html",
                {
                    "request": request,
                    "appid": appid,
                    "achievements": achievements_data,
                    "game_name": game_name,
                    "background": background_url,
                    "now": now
                },
            )
        except Exception as e:
            logging.error(f"Ошибка выборки ачивок: {str(e)}")
            print(f"An error occurred while fetching games: {str(e)}")
            return {"error": "Failed to fetch games data"}


# Функция отправки пуша

VAPID_PRIVATE_KEY_PATH = os.getenv("VAPID_PRIVATE_KEY_PATH")
VAPID_CLAIMS = {
    "sub": os.getenv("VAPID_CLAIMS")
}


def send_push_notification(subscription, title, body, icon, url):
    payload = {
        "title": title,
        "body": body,
        "icon": icon,
        "url": url
    }

    subscription_info = {
        "endpoint": subscription.endpoint,
        "keys": {
            "p256dh": subscription.p256dh,
            "auth": subscription.auth
        }
    }

    try:
        response = webpush(
            subscription_info=subscription_info,
            data=json.dumps(payload),
            vapid_private_key=VAPID_PRIVATE_KEY_PATH,
            vapid_claims=VAPID_CLAIMS
        )
        logging.info(f"Push отправлен.Содержимое {payload} Статус: {response.status_code}")
    except WebPushException as ex:
        logging.error(f"Ошибка при отправке push: {repr(ex)} | Endpoint: {subscription.endpoint}")

        if "404" in str(ex):
            try:
                with SyncSessionLocal() as db:
                    db_subscription = db.query(PushSubscription).filter_by(endpoint=subscription.endpoint).first()
                    if db_subscription:
                        db.delete(db_subscription)
                        db.commit()
                        logging.info(f"Удалена подписка с endpoint: {subscription.endpoint}")
            except Exception as e:
                logging.error(f"Ошибка при удалении подписки: {e}")


class AchievementData(BaseModel):
    appid: int
    achievement_name: str
    obtained_time: int
    user_id: int

#поиск релизов
@app.get("/api/search")
async def search_releases(q: str = Query(..., min_length=2)):
    async with SessionLocal() as session:
        # stmt = (
        #     select(Release)
        #     .where(Release.name.ilike(f"%{q}%"))
        #     .where(Release.type == 'game')
        #     .limit(10)
        # )
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
            {
                "name": r.name,
                "appid": r.appid,
                "release_date": r.release_date
            }
            for r in releases
        ]

# Эндпоинт для получения данных и обновления достижения
@app.post("/api/update_achievement")
async def update_achievement_endpoint(data: AchievementData):
    async with SessionLocal() as session:
        await update_achievement(
            session=session,
            appid=data.appid,
            achievement_name=data.achievement_name,
            obtained_time=data.obtained_time,
            user_id=data.user_id
        )
        logging.info(f"Отправили ачивку с удаленного вебсокета, {data.achievement_name}")
        return {"message": "Achievement updated successfully"}


async def get_user_favorites(user_id: int, session: AsyncSession) -> list[int]:
    query = select(Favorite.appid).where(Favorite.user_id == user_id)
    result = await session.execute(query)
    return [row[0] for row in result.fetchall()]


# Функция обновления достижений
async def update_achievement(
        session: AsyncSession,
        appid: int,
        achievement_name: str,
        obtained_time: int,
        user_id: int,
):
    obtained_date = datetime.utcfromtimestamp(obtained_time)

    query = select(Achievement).where(
        Achievement.appid == appid,
        Achievement.name == achievement_name,
        Achievement.user_id == user_id
    )
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

        # Пуш рассылки
        async with SessionLocal() as db:
            subscriptions = await db.execute(
                select(PushSubscription).where(PushSubscription.user_id == user_id)
            )
            for sub in subscriptions.scalars():
                send_push_notification(sub, title, body, icon, url)

        appid = achievement.appid

        # 2. Получаем название игры из таблицы games по appid
        result = await db.execute(select(Game).filter(Game.appid == appid).filter(Game.user_id == user_id))
        game = result.scalars().first()

        if game is None:
            return {"error": "Игра не найдена"}

        game_name = game.name

        title = achievement.displayname
        body = f"Вы получили достижение: {title}"
        icon = achievement.icon
        url = achievement.icongray

        # Обновляем сообщение для Telegram с названием игры
        message = f"Ачивка в игре {game_name }: {title}\nСсылка: {url}"

        # Отправляем сообщение и изображение в Telegram
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
                        # Прибавляем 3 часа прямо здесь, чтобы не делать это в update_achievement
                        obtained_time = int(data["time"]) + 3 * 3600  # Добавляем 3 часа (в секундах)

                        # Здесь создаем фоновую задачу
                        asyncio.create_task(update_achievement(
                            session,
                            int(data["appID"]),
                            data["achievement"],
                            obtained_time,
                            user_id
                        ))
                        logging.info("Отправили ачивку с локального вебсокета")
        except Exception as e:
            # logging.error(f"Ошибка веб-сокета: {e}")
            # print(f"Ошибка веб-сокета: {e}")
            await asyncio.sleep(5)  # Ждем перед повторным подключением


@app.post("/add_game")
async def add_game(request: Request, user=Depends(manager)):
    # Открываем сессию с базой данных
    async with SessionLocal() as db:
        # Читаем "сырые" данные из запроса
        data = await request.json()
        logging.info(f"Получены данные игры: {data}")
        print(f"🔍 Raw JSON received: {data}")  # Логируем полученные данные

        try:
            appid = int(data["appid"])  # Преобразуем appid в int
        except (KeyError, ValueError):
            logging.error("Некорректный формат appid")
            raise HTTPException(
                status_code=400, detail="Некорректный формат appid"
            )

        logging.info(f"Спарсили appid: {appid}")
        print(f"✅ Parsed appid: {appid}")  # Логируем, если удалось распарсить

        # Дальше выполняем оригинальную логику:
        existing_game = await db.execute(
            select(Game).filter(Game.appid == appid).filter(Game.user_id == user.id)
        )
        if existing_game.scalar_one_or_none():
            logging.error("Игра уже добавлена")
            raise HTTPException(status_code=400, detail="Игра уже добавлена")

        game_data = await fetch_game_data(appid)
        if not game_data or "game" not in game_data:
            logging.error("Игра не найдена в Steam")
            raise HTTPException(
                status_code=404, detail="Игра не найдена в Steam"
            )

        game_name = game_data["game"]["gameName"]

        # Добавляем игру в базу
        new_game = Game(appid=appid, name=game_name, user_id=user.id)
        db.add(new_game)

        achievements = (
            game_data["game"]
            .get("availableGameStats", {})
            .get("achievements", [])
        )
        for ach in achievements:
            # Генерация URL для иконки
            icongray_url = await get_achievement_url(
                game_name, ach["displayName"]
            )

            achievement = Achievement(
                appid=appid,  # Ссылаемся на appid игры
                name=ach["name"],
                displayname=ach["displayName"],
                defaultval=ach.get(
                    "defaultValue", 0
                ),  # Добавляем defaultval, если оно есть
                hidden=ach.get("hidden", 0),  # Добавляем hidden, если оно есть
                icon=ach.get("icon", ""),  # Если есть иконка
                icongray=icongray_url,  # Добавляем ссылку на иконку
                obtained_date=None,  # Не получено на старте
                user_id=user.id  # ид пользователя
            )
            db.add(achievement)

        try:
            await db.commit()
            logging.info("Игра и достижения добавлены")
            return {"message": "Игра и достижения добавлены"}
        except IntegrityError:
            await db.rollback()
            logging.error("Ошибка при добавлении игры")
            raise HTTPException(
                status_code=500, detail="Ошибка при добавлении игры"
            )


# Настроим логирование
# logging.basicConfig(level=logging.DEBUG)

@app.post("/update_paths")
async def update_paths(request: Request, user=Depends(manager)):
    # Открываем сессию с базой данных
    async with SessionLocal() as db:
        data = await request.json()
        logging.info(f"Получили данные по игре: {data}")
        print(f"🔍 Raw JSON received: {data}")  # Логируем полученные данные

        # Извлекаем данные из запроса
        appid = data.get("appid")
        old_substring = data.get("oldSubstring")
        new_substring = data.get("newSubstring")

        # Проверка на корректность данных
        if not all([appid, old_substring, new_substring]):
            logging.error("Все поля должны быть заполнены")
            raise HTTPException(
                status_code=400, detail="Все поля должны быть заполнены"
            )

        try:
            appid = int(appid)  # Преобразуем appid в int
        except ValueError:
            logging.error("Некорректный формат appid")
            raise HTTPException(
                status_code=400, detail="Некорректный формат appid"
            )

        # Логируем, если всё в порядке
        logging.info(f"Спарсили успешно: {appid}")
        print(f"✅ Parsed appid: {appid}")

        try:
            # Выполняем запрос для обновления путей
            query = text(
                """
                UPDATE achievements
                SET icongray = REPLACE(icongray, :old_substring, :new_substring)
                WHERE appid = :appid AND user_id = :user_id
            """
            )
            await db.execute(
                query,
                {
                    "appid": appid,
                    "old_substring": old_substring,
                    "new_substring": new_substring,
                    "user_id": user.id,
                },
            )
            await db.commit()

            logging.info("Пути обновлены успешно")
            return {"success": True, "message": "Пути обновлены успешно"}

        except Exception as e:
            logging.error("Ошибка при обновлении путей: %s", str(e))
            await db.rollback()  # Откатить транзакцию в случае ошибки
            raise HTTPException(
                status_code=500,
                detail=f"Ошибка при обновлении путей: {str(e)}",
            )


# Модель для тестового уведомления
class TestPushNotification(BaseModel):
    title: str
    body: str
    icon: str
    url: str


@app.get("/send_test_notification")
async def send_test_notification():
    # Данные для тестового пуш-уведомления
    achiev_name = "ACH_Branch_BloodyMary"

    async with SessionLocal() as db:
        # 1. Получаем appid из таблицы achievements по названию достижения
        result = await db.execute(
            select(Achievement).where(Achievement.name == achiev_name).where(Achievement.user_id == 1))
        achievement = result.scalars().first()

        if achievement is None:
            return {"error": "Достижение не найдено"}

        appid = achievement.appid

        # 2. Получаем название игры из таблицы games по appid
        result = await db.execute(select(Game).filter(Game.appid == appid).filter(Game.user_id == 1))
        game = result.scalars().first()

        if game is None:
            return {"error": "Игра не найдена"}

        game_name = game.name

        title = achievement.displayname
        body = f"Вы получили достижение: {title}"
        icon = achievement.icon
        url = achievement.icongray

        # Обновляем сообщение для Telegram с названием игры
        message = f"Ачивка в игре {game_name}: {title}\nСсылка: {url}"

        # Извлекаем все подписки из базы данных
        subscriptions_result = await db.execute(select(PushSubscription))
        subscriptions = subscriptions_result.scalars().all()

        # Отправка уведомления каждой подписке
        for sub in subscriptions:
            send_push_notification(sub, title, body, icon, url)

        # Отправляем сообщение и изображение в Telegram
        for user_id, telegram_id in user_to_telegram.items():
            send_telegram_message_with_image(telegram_id, message, BOT_TOKEN, icon)
            logging.error(f"Отправили уведомление в телеграм {title} юзеру {telegram_id}")

    return {"message": "Тестовое уведомление отправлено"}


def send_telegram_message_with_image(chat_id: int, message: str, bot_token: str, image_url: str):
    # URL для отправки фото
    url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"

    # Формируем параметры запроса
    payload = {
        "chat_id": chat_id,
        "caption": message,  # Текстовое сообщение
        "parse_mode": "HTML",  # Поддержка HTML-разметки
        "photo": image_url  # URL изображения
    }

    # Отправляем запрос
    response = requests.post(url, data=payload)
    logging.info(f"Данные в телегу {payload}")
    logging.info(f"Запрос в телегу {response}")
    return response
