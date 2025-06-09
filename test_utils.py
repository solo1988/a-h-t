# Пример: получить топ 20 ожидаемых игр для ПК с RAWG
import requests

API_KEY = "01dfc51073714f4db8898b2fc7796499"
url = "https://api.rawg.io/api/games"
params = {
    "platforms": 4,  # PC
    "dates": "2025-06-01,2026-12-31",
    "ordering": "-added",
    "page_size": 20,
    "key": API_KEY
}

response = requests.get(url, params=params)
games = response.json()["results"]
for g in games:
    print(f"{g['name']} — {g['released']} (Добавлений: {g['added']})")