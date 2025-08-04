import logging

# Логгер релизов
logger = logging.getLogger("releases")
logger.setLevel(logging.INFO)
logger.propagate = False

file_handler = logging.FileHandler("releases.log", encoding="utf-8")
formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

# Логгер обновлений
logger_update = logging.getLogger("updater")
logger_update.setLevel(logging.INFO)
logger_update.propagate = False

file_handler_update = logging.FileHandler("updater.log", encoding="utf-8")
formatter_update = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
file_handler_update.setFormatter(formatter_update)  # <- здесь должно быть file_handler_update
logger_update.addHandler(file_handler_update)

# Логгер приложения
logger_app = logging.getLogger("app")  # Лучше уникальное имя, например "app"
logger_app.setLevel(logging.INFO)
logger_app.propagate = False

file_handler_app = logging.FileHandler("app.log", encoding="utf-8")
formatter_app = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
file_handler_app.setFormatter(formatter_app)
logger_app.addHandler(file_handler_app)

# Отключаем логирование для сторонних библиотек, чтобы не засорять логи
logging.getLogger("apscheduler").propagate = False
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
