import requests
import json
import httpx

from app.core.logger import logger_app


def send_telegram_message_with_image(chat_id: int, message: str, bot_token: str, image_url: str):
    url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
    payload = {"chat_id": chat_id, "caption": message, "parse_mode": "HTML", "photo": image_url}
    try:
        response = requests.post(url, data=payload, timeout=15)
        response.raise_for_status()
        logger_app.info("Сообщение успешно отправлено в Telegram")
        return response
    except requests.exceptions.Timeout:
        logger_app.error("Timeout при отправке сообщения в Telegram")
    except requests.exceptions.RequestException as e:
        logger_app.error(f"Ошибка при отправке сообщения в Telegram: {e}")
    return None

async def send_telegram_message_with_image_async(chat_id: int, message: str, bot_token: str, image_url: str, buttons: list[dict]):
    url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"

    # Добавляем хэштег, если его нет
    if "#релиз" not in message:
        message += "\n\n#релиз"

    reply_markup = {
        "inline_keyboard": [buttons]
    }

    payload = {
        "chat_id": chat_id,
        "caption": message,
        "parse_mode": "HTML",
        "photo": image_url,
        "reply_markup": json.dumps(reply_markup)
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(url, data=payload)
        response_data = response.json()

        if not response_data.get("ok"):
            print(f"[send_telegram_message] Ошибка отправки сообщения: {response_data}")
            return response

        # Получаем message_id отправленного сообщения
        message_id = response_data["result"]["message_id"]

        # Пытаемся закрепить сообщение
        pin_url = f"https://api.telegram.org/bot{bot_token}/pinChatMessage"
        pin_payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "disable_notification": True  # без уведомления
        }

        try:
            pin_response = await client.post(pin_url, data=pin_payload)
            pin_data = pin_response.json()
            if not pin_data.get("ok"):
                print(f"[pinChatMessage] Не удалось закрепить сообщение: {pin_data}")
        except Exception as e:
            print(f"[pinChatMessage] Исключение при попытке закрепить сообщение: {e}")

        return response