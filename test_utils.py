import asyncio
import aiohttp
import aiofiles
from sqlalchemy.orm import Session
from database import SyncSessionLocal
from models import Release
import json
import os

MODIFIED_SINCE_FILE = "modified_since.txt"
GET_APP_LIST_URL = "https://api.steampowered.com/IStoreService/GetAppList/v1/"
MAX_GENRE_RETRIES = 5
SKIP_FILE = "genre_retry.json"

def load_genre_retries():
    if os.path.exists(SKIP_FILE):
        with open(SKIP_FILE, "r") as f:
            return json.load(f)
    return {}

async def update_release_dates():
    db: Session = SyncSessionLocal()
    genre_retries = load_genre_retries()
    skip_appids = [int(appid) for appid, count in genre_retries.items() if count >= MAX_GENRE_RETRIES]

    try:
        async with aiofiles.open(MODIFIED_SINCE_FILE, mode='r') as f:
            if_modified_since = int((await f.read()).strip())
    except Exception:
        if_modified_since = 0

    appids = []
    max_last_modified = if_modified_since

    url = f"{GET_APP_LIST_URL}?key=F7BA516A3C38043AFFAADA7A6A31CD82&if_modified_since={if_modified_since}&include_games=1"

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            data = await response.json()

    applist = data.get("response", {}).get("apps", [])
    for app in applist:
        appid = int(app.get("appid"))
        last_modified = app.get("last_modified", 0)
        if appid:
            appids.append(appid)
        if last_modified > max_last_modified:
            max_last_modified = last_modified

    games_to_update = list(
        db.query(Release)
        .filter(
            Release.type == 'game',
            Release.appid.in_(appids),
            Release.appid.notin_(skip_appids)
        )
        .order_by(Release.appid.desc())
    )

    print(f"Всего отобрано к обновлению: {len(games_to_update)} игр")

    print(f"Всего appids получено: {len(appids)}")
    #print(f"Примеры appids: {appids}")

    # async with aiofiles.open(MODIFIED_SINCE_FILE, mode='w') as f:
    #     await f.write(str(max_last_modified))

    db.close()

if __name__ == "__main__":
    asyncio.run(update_release_dates())