import re
import httpx
from urllib.parse import quote
import logging
import os
from dotenv import load_dotenv


STEAM_API_KEY = os.getenv("STEAM_API_KEY")
STEAM_API_URL = "https://api.steampowered.com/ISteamUserStats/GetSchemaForGame/v2/"

async def get_achievement_url(game_name: str, displayname: str):
    # Формируем URL игры с преобразованием названия
    game_name_slug = game_name.lower().replace("&amp;", "").replace("&", "_").replace(" ", "_").replace(":", "")
    # Заменим два подчеркивания подряд на одно
    game_name_slug = game_name_slug.replace("__", "_")

    achievement_slug = displayname.lower().replace(" ", "_").replace("!", "_voskl").replace("’", "").replace("'", "")
    achievement_slug = achievement_slug.replace("__", "_")

    url = f"https://stratege.ru/ps5/trophies/{game_name_slug}/spisok/{achievement_slug}"
    return url


async def fetch_game_data(appid: int):
    async with httpx.AsyncClient() as client:
        url = f"{STEAM_API_URL}?key={STEAM_API_KEY}&appid={appid}"
        response = await client.get(url)
        if response.status_code == 200:
            game_data = response.json()
            logging.info(f"Получили данные от стима: {game_data}")
            print(game_data)  # Добавь вывод для проверки структуры данных
            return game_data
    return None
