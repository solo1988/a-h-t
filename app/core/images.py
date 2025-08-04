import aiohttp
from pathlib import Path
from app.core.config import settings


async def check_background_exists_local(appid: int) -> bool:
    return (settings.BACKGROUND_DIR / f"{appid}.jpg").exists()


async def ensure_background_image(session: aiohttp.ClientSession, appid: int) -> str:
    settings.BACKGROUND_DIR.mkdir(parents=True, exist_ok=True)
    local_path = settings.BACKGROUND_DIR / f"{appid}.jpg"

    if await check_background_exists_local(appid):
        return f"/static/images/background/{appid}.jpg"

    background_url = f"https://cdn.steamstatic.com/steam/apps/{appid}/library_hero.jpg"
    if await download_image(session, background_url, local_path):
        return f"/static/images/background/{appid}.jpg"

    return ""


async def check_image_exists_local(appid: int) -> bool:
    return (settings.STATIC_DIR / f"{appid}.jpg").exists()


async def download_header_image(appid: int, session: aiohttp.ClientSession):
    await ensure_header_image(session, appid)


async def download_image(session: aiohttp.ClientSession, url: str, path: Path) -> bool:
    try:
        async with session.get(url) as resp:
            if resp.status == 200:
                with open(path, "wb") as f:
                    f.write(await resp.read())
                return True
            else:
                print(f"[Загрузка] Не удалось скачать изображение: {url}, статус {resp.status}")
    except Exception as e:

        print(f"[Ошибка загрузки] {url} — {e}")
    return False


async def get_header_image_url_from_api(session: aiohttp.ClientSession, appid: int) -> str:
    api_url = f"https://store.steampowered.com/api/appdetails?appids={appid}"
    try:
        async with session.get(api_url) as resp:
            if resp.status == 200:
                data = await resp.json()
                entry = data.get(str(appid), {})
                if entry.get("success") and "data" in entry:
                    return entry["data"].get("header_image", "")
    except Exception as e:
        print(f"[Steam API] Ошибка получения header_image для {appid}: {e}")
    return ""


async def ensure_header_image(session: aiohttp.ClientSession, appid: int) -> str:
    settings.STATIC_DIR.mkdir(parents=True, exist_ok=True)
    local_path = settings.STATIC_DIR / f"{appid}.jpg"
    if await check_image_exists_local(appid):
        return f"/static/images/header/{appid}.jpg"

    # 1. Пробуем CDN
    cdn_url = f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/header.jpg"
    if await download_image(session, cdn_url, local_path):
        return f"/static/images/header/{appid}.jpg"

    # 2. Пробуем Steam API
    header_url = await get_header_image_url_from_api(session, appid)

    if header_url and await download_image(session, header_url, local_path):
        return f"/static/images/header/{appid}.jpg"

    return ""
