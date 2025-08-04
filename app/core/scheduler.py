from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from pytz import timezone

from app.core.logger import logger
from app.core.games import check_daily_releases

def start_scheduler():
    scheduler = AsyncIOScheduler()
    logger.info("[check_favorites] Планировщик запущен")
    scheduler.add_job(
        check_daily_releases,
        CronTrigger(hour=11, minute=0, timezone=timezone("Europe/Moscow")),
        misfire_grace_time=300
    )
    scheduler.start()
    return scheduler