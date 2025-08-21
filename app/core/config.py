import os
from pathlib import Path
from dotenv import load_dotenv
from fastapi_login import LoginManager
from passlib.context import CryptContext

load_dotenv()


class Settings:
    SECRET_KEY = os.getenv("SECRET_KEY")
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    VAPID_PRIVATE_KEY_PATH = os.getenv("VAPID_PRIVATE_KEY_PATH")
    VAPID_CLAIMS = {"sub": os.getenv("VAPID_CLAIMS")}
    ALLOWED_USER_ID = int(os.getenv("ALLOWED_USER_ID"))
    TELEGRAM_IDS = [int(t.strip()) for t in os.getenv("TELEGRAM_IDS", "").split(",") if t.strip()]
    USER_IDS = [1, 2]
    USER_TO_TELEGRAM_ID = {
        1: 558950992,
        2: 731299888,
    }
    USER_TO_TELEGRAM = dict(zip(USER_IDS, TELEGRAM_IDS))
    EXCLUDED_GENRES = {"4", "23", "57", "55", "51"}

    MONTHS_MAP = {
        1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
        7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec"
    }
    MONTHS_MAP_RUSSIAN = {
        1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель", 5: "Май", 6: "Июнь",
        7: "Июль", 8: "Август", 9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь"
    }
    MONTHS_MAP_REV = {v: k for k, v in MONTHS_MAP.items()}
    RUSSIAN_MONTHS = {
        # Январь
        "янв": 1, "янв.": 1, "январь": 1, "января": 1,
        # Февраль
        "фев": 2, "фев.": 2, "февраль": 2, "февраля": 2,
        # Март
        "мар": 3, "мар.": 3, "март": 3, "марта": 3,
        # Апрель
        "апр": 4, "апр.": 4, "апрель": 4, "апреля": 4,
        # Май
        "май": 5, "мая": 5,
        # Июнь
        "июн": 6, "июн.": 6, "июнь": 6, "июня": 6,
        # Июль
        "июл": 7, "июл.": 7, "июль": 7, "июля": 7,
        # Август
        "авг": 8, "авг.": 8, "август": 8, "августа": 8,
        # Сентябрь
        "сен": 9, "сен.": 9, "сент": 9, "сент.": 9, "сентябрь": 9, "сентября": 9,
        # Октябрь
        "окт": 10, "окт.": 10, "октябрь": 10, "октября": 10,
        # Ноябрь
        "ноя": 11, "ноя.": 11, "нояб": 11, "нояб.": 11, "ноябрь": 11, "ноября": 11,
        # Декабрь
        "дек": 12, "дек.": 12, "декабрь": 12, "декабря": 12,
    }
    UNCERTAIN_DATE_PATTERNS = [
        "To be announced", "Скоро выйдет",
        "Q1", "Q2", "Q3", "Q4"
    ]
    MONTH_NAMES = [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December"
    ]

    MAX_GENRE_RETRIES = 5
    BASE_DIR = Path(__file__).resolve().parent.parent.parent  # корень проекта (если config.py в /app/core/)
    DATA_DIR = BASE_DIR / "data"
    SKIP_FILE = DATA_DIR / "genre_retry.json"

    STEAM_API_KEY = os.getenv("STEAM_API_KEY")
    STEAM_API_URL = "https://api.steampowered.com/ISteamUserStats/GetSchemaForGame/v2/"
    GET_APP_LIST_URL = "https://api.steampowered.com/IStoreService/GetAppList/v1/"
    FETCH_APP_URL = "https://api.steampowered.com/ISteamApps/GetAppList/v2/"
    MODIFIED_SINCE_FILE = DATA_DIR / "modified_since.txt"
    DATABASE_PATH = DATA_DIR / "games.db"

    STATIC_DIR = Path(__file__).parent / "static" / "images" / "header"
    BACKGROUND_DIR = Path(__file__).parent / "static" / "images" / "background"

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
        6: 'Июня', 7: 'Июля', 8: 'Августа', 9: 'сентября', 10: 'Октября',
        11: 'Ноября', 12: 'Декабря'
    }

    RU_MONTHS_ABBR = {
        1: 'янв.', 2: 'февр.', 3: 'мар.', 4: 'апр.', 5: 'мая', 6: 'июн.',
        7: 'июл.', 8: 'авг.', 9: 'сен.', 10: 'окт.', 11: 'ноя.', 12: 'дек.'
    }

    RAWG_API_KEY = "01dfc51073714f4db8898b2fc7796499"
    RAWG_URL = "https://api.rawg.io/api/games"

settings = Settings()
