import asyncio
import functools
import json

from app.core.config import settings
from app.core.logger import logger_app
from pywebpush import webpush, WebPushException
from app.core.database import SessionLocal
from sqlalchemy.future import select
from app.models import PushSubscription

async def send_push_notification_async(subscription, title, body, icon, url):
    loop = asyncio.get_event_loop()
    max_retries = 3
    delay_seconds = 5

    for attempt in range(max_retries):
        try:
            await loop.run_in_executor(
                None,
                functools.partial(
                    webpush,
                    subscription_info={"endpoint": subscription.endpoint, "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth, }, },
                    data=json.dumps({"title": title, "body": body, "icon": icon, "url": url, }),
                    vapid_private_key=settings.VAPID_PRIVATE_KEY_PATH,
                    vapid_claims=settings.VAPID_CLAIMS,
                    timeout=30
                )
            )
            break

        except WebPushException as ex:
            logger_app.error(f"Ошибка отправки push: {repr(ex)}")

            if "404" in str(ex) or "410" in str(ex):
                async with SessionLocal() as db:
                    sub_db = await db.execute(select(PushSubscription).where(PushSubscription.endpoint == subscription.endpoint))
                    sub_obj = sub_db.scalar_one_or_none()
                    if sub_obj:
                        await db.delete(sub_obj)
                        await db.commit()
                        logger_app.info(f"Удалена подписка с endpoint {subscription.endpoint}")
                break

            else:
                logger_app.info(f"Попытка {attempt + 1} из {max_retries} не удалась, повтор через {delay_seconds} сек")
                await asyncio.sleep(delay_seconds)

        except Exception as e:
            logger_app.error(f"Неожиданная ошибка при отправке push: {e}")
            logger_app.info(f"Попытка {attempt + 1} из {max_retries} не удалась, повтор через {delay_seconds} сек")
            await asyncio.sleep(delay_seconds)

    else:
        logger_app.error(f"Не удалось отправить push после {max_retries} попыток")