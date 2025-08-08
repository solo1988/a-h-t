import logging
from datetime import datetime
import os
from pathlib import Path

# Абсолютный путь до корня проекта
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Папка для логов
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

# Пути до лог-файлов
updater_log_path = LOG_DIR / "updater.log"
releases_log_path = LOG_DIR / "releases.log"
app_log_path = LOG_DIR / "app.log"

# Удаляем updater.log, если он относится к предыдущему дню
if updater_log_path.exists():
    last_modified = datetime.fromtimestamp(updater_log_path.stat().st_mtime)
    if last_modified.date() != datetime.now().date():
        updater_log_path.unlink()

# Формат логов
formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

# Логгер релизов
logger = logging.getLogger("releases")
logger.setLevel(logging.INFO)
logger.propagate = False

file_handler = logging.FileHandler(releases_log_path, encoding="utf-8")
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

# Логгер обновлений
logger_update = logging.getLogger("updater")
logger_update.setLevel(logging.INFO)
logger_update.propagate = False

file_handler_update = logging.FileHandler(updater_log_path, encoding="utf-8")
file_handler_update.setFormatter(formatter)
logger_update.addHandler(file_handler_update)

# Логгер приложения
logger_app = logging.getLogger("app")
logger_app.setLevel(logging.INFO)
logger_app.propagate = False

file_handler_app = logging.FileHandler(app_log_path, encoding="utf-8")
file_handler_app.setFormatter(formatter)
logger_app.addHandler(file_handler_app)

# Отключаем лишние логи от сторонних библиотек
logging.getLogger("apscheduler").propagate = False
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)