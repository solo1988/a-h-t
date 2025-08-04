from fastapi_login import LoginManager
from passlib.context import CryptContext
from sqlalchemy.future import select

from app.models import User
from app.core.config import settings
from app.core.database import SessionLocal

# Создание LoginManager
manager = LoginManager(
    settings.SECRET_KEY,
    token_url="/login",
    use_cookie=True
)
manager.cookie_name = "auth_token"
manager.lifetime_seconds = 31536000

# Хеширование паролей
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Асинхронная функция загрузки пользователя
async def load_user(username: str):
    async with SessionLocal() as session:
        result = await session.execute(select(User).where(User.username == username))
        return result.scalar_one_or_none()

# Привязка функции к менеджеру
manager.user_loader()(load_user)