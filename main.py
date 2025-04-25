import asyncio
import json
import websockets
from datetime import datetime
from pydantic import BaseModel
from steam_api import fetch_game_data, get_achievement_url
from fastapi import FastAPI, Depends, HTTPException, Request, BackgroundTasks, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse
from database import init_db, SessionLocal
from crud import get_games, get_achievements_for_game, get_game_name
from models import Achievement, Game, PushSubscription, PushSubscriptionCreate
from sqlalchemy.future import select
from sqlalchemy.exc import IntegrityError
import uvicorn
import hashlib
import hmac
import time
from starlette.middleware.sessions import SessionMiddleware
import logging
import sqlite3
from typing import Dict
import requests
from pywebpush import webpush, WebPushException
import os
from dotenv import load_dotenv


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


# Настройка логирования
logging.basicConfig(
    filename="app.log",  # Имя файла для записи логов
    level=logging.ERROR,  # Уровень логирования
    format="%(asctime)s - %(levelname)s - %(message)s",  # Формат сообщений
)


@app.post("/subscribe")
async def subscribe(subscription: PushSubscriptionCreate):
    async with SessionLocal() as db:
        new_sub = PushSubscription(
            endpoint=subscription.endpoint,
            p256dh=subscription.p256dh,
            auth=subscription.auth,
        )
        db.add(new_sub)
        try:
            await db.commit()
            logging.info("Подписка сохранена")
            return {"message": "Подписка сохранена"}
        except Exception as e:
            await db.rollback()
            logging.error(f"Ошибка: {e}")
            raise HTTPException(status_code=500, detail=f"Ошибка: {e}")


def check_telegram_auth(data: dict) -> bool:
    """
    Проверяет подпись Telegram для защиты от подмены данных
    """
    auth_data = data.copy()
    hash_check = auth_data.pop("hash")
    sorted_data = "\n".join(f"{k}={v}" for k, v in sorted(auth_data.items()))
    secret_key = hashlib.sha256(BOT_TOKEN.encode()).digest()
    calculated_hash = hmac.new(
        secret_key, sorted_data.encode(), hashlib.sha256
    ).hexdigest()

    # Проверяем подпись
    if calculated_hash != hash_check:
        return False

    # Проверяем, что данные получены недавно (защита от повторного использования)
    auth_time = int(auth_data.get("auth_date", 0))
    if time.time() - auth_time > 86400:  # 24 часа
        return False

    return True


@app.get("/auth")
async def auth(request: Request):
    data = dict(request.query_params)

    if not check_telegram_auth(data):
        logging.error("Ошибка аутентификации Telegram")
        raise HTTPException(
            status_code=403, detail="Ошибка аутентификации Telegram"
        )

    user_id = int(data["id"])

    if user_id != int(ALLOWED_USER_ID):
        logging.error("Доступ запрещён")
        raise HTTPException(status_code=403, detail=f"Доступ запрещён:{user_id} -  {ALLOWED_USER_ID}")

    # ✅ Сохраняем авторизованного пользователя в сессии
    request.session["user_id"] = user_id
    return RedirectResponse(url="/")


@app.get("/check_auth")
async def check_auth(request: Request):
    """
    Проверяет, авторизован ли пользователь
    """
    user_id = request.session.get("user_id")
    if user_id == ALLOWED_USER_ID:
        return JSONResponse({"authenticated": True})
    return JSONResponse({"authenticated": False})


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


# Главная страница с выводом списка игр
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    # Открываем сессию с базой данных
    async with SessionLocal() as session:
        try:
            # Получаем список игр из базы данных
            games = await get_games(
                session
            )  # предполагаем, что get_games возвращает список игр
            logging.info("Загружена главная страница")
            return templates.TemplateResponse(
                "index.html", {"request": request, "games": games}
            )
        except Exception as e:
            logging.error(f"Ошибка выборки игр главной страницы: {str(e)}")
            print(f"An error occurred while fetching games: {str(e)}")
            raise HTTPException(
                status_code=500, detail=f"Failed to fetch games data: {str(e)}"
            )


# Страница достижений
@app.get("/achievements/{appid}", response_class=HTMLResponse)
async def achievements(request: Request, appid: int):
    # Получаем данные о достижениях из базы данных
    # Проверяем, авторизован ли пользователь
    user_id = request.session.get("user_id")
    if user_id != ALLOWED_USER_ID:
        return RedirectResponse(url="/")
    async with SessionLocal() as session:
        try:
            achievements = await get_achievements_for_game(session, appid)
            game_name = await get_game_name(session, appid)
            background_url = f"/static/images/background/{appid}.jpg"

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

            logging.info("Загружена страница ачивок")
            return templates.TemplateResponse(
                "achievements.html",
                {
                    "request": request,
                    "appid": appid,
                    "achievements": achievements_data,
                    "game_name": game_name,
                    "background": background_url,
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
        logging.error(f"Ошибка при отправке push: {repr(ex)}")


# Функция обновления достижений
async def update_achievement(
        session: AsyncSession,
        appid: int,
        achievement_name: str,
        obtained_time: int,
):
    obtained_date = datetime.utcfromtimestamp(obtained_time)

    query = select(Achievement).where(
        Achievement.appid == appid,
        Achievement.name == achievement_name
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

        async with SessionLocal() as db:
            subscriptions = await db.execute(select(PushSubscription))
            for sub in subscriptions.scalars():
                send_push_notification(sub, title, body, icon, url)

        appid = achievement.appid

        # 2. Получаем название игры из таблицы games по appid
        result = await db.execute(select(Game).filter(Game.appid == appid))
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
        send_telegram_message_with_image(ALLOWED_USER_ID, message, BOT_TOKEN, icon)
        logging.info(f"Отправили уведомление в телеграм {title}")



async def websocket_listener():
    uri = "ws://192.168.1.111:8082"
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
                        ))
        except Exception as e:
            logging.error(f"Ошибка веб-сокета: {e}")
            print(f"Ошибка веб-сокета: {e}")
            await asyncio.sleep(5)  # Ждем перед повторным подключением

@app.post("/add_game")
async def add_game(request: Request):
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
            select(Game).filter(Game.appid == appid)
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
        new_game = Game(appid=appid, name=game_name)
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
async def update_paths(request: Request):
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
                WHERE appid = :appid
            """
            )
            await db.execute(
                query,
                {
                    "appid": appid,
                    "old_substring": old_substring,
                    "new_substring": new_substring,
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
        result = await db.execute(select(Achievement).where(Achievement.name == achiev_name))
        achievement = result.scalars().first()

        if achievement is None:
            return {"error": "Достижение не найдено"}

        appid = achievement.appid

        # 2. Получаем название игры из таблицы games по appid
        result = await db.execute(select(Game).filter(Game.appid == appid))
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
        send_telegram_message_with_image(ALLOWED_USER_ID, message, BOT_TOKEN, icon)
        logging.info(f"Отправили уведомление в телеграм {title}")

    return {"message": "Тестовое уведомление отправлено"}


def send_telegram_message_with_image(chat_id: str, message: str, bot_token: str, image_url: str):
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
