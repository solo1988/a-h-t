import os
import json

from app.core.config import settings

def load_genre_retries():
    if os.path.exists(settings.SKIP_FILE):
        with open(settings.SKIP_FILE, "r") as f:
            return json.load(f)
    return {}


def save_genre_retries(retries):
    with open(settings.SKIP_FILE, "w") as f:
        json.dump(retries, f)