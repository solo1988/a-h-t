import os
import json

from app.core.config import settings

def load_genre_retries():
    if os.path.exists(str(settings.SKIP_FILE)):
        with open(str(settings.SKIP_FILE), "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_genre_retries(retries):
    with open(str(settings.SKIP_FILE), "w", encoding="utf-8") as f:
        json.dump(retries, f, ensure_ascii=False, indent=2)
