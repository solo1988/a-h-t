from asyncio import get_event_loop
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from pytz import timezone
from datetime import datetime
import traceback

from app.core.logger import logger
from app.core.games import check_daily_releases

def start_scheduler():
    loop = get_event_loop()
    scheduler = AsyncIOScheduler(event_loop=loop)
    logger.info("[check_favorites] Планировщик запущен")

    def job_wrapper():
        logger.info("[check_favorites] Запуск задачи check_daily_releases")
        try:
            loop.create_task(check_daily_releases())
        except Exception as e:
            logger.error(f"[check_favorites] Ошибка при запуске задачи: {e}")
            logger.error(traceback.format_exc())

    scheduler.add_job(
        job_wrapper,
        CronTrigger(hour=9, minute=0, timezone=timezone("Europe/Moscow")),
        misfire_grace_time=300,
        id="check_daily_releases_job",
        coalesce=True,
        max_instances=1,
        # next_run_time=datetime.now()
    )
    scheduler.start()
    return scheduler
