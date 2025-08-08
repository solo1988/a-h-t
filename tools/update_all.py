import asyncio
from app.core.games import update_games_db, update_release_dates

update_games_db()
asyncio.run(update_release_dates())