import asyncio
from steam_releases_updater import update_games_db, update_release_dates

update_games_db()
asyncio.run(update_release_dates())  # ✅ правильно — исполняется асинхронно