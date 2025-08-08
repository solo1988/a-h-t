from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Boolean, Date, func
from sqlalchemy.orm import relationship
from app.core.database import Base
from pydantic import BaseModel


class ArchivedGame(Base):
    __tablename__ = "archived_games"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True)
    appid = Column(Integer, index=True)
    archived_at = Column(DateTime, default=func.now())

class Wanted(Base):
    __tablename__ = "wanted"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    rawg_id = Column(Integer, nullable=True)
    added = Column(Integer, nullable=True)
    release_date = Column(Date, nullable=True)
    appid = Column(Integer, nullable=True)  # Связь с таблицей releases

class Favorite(Base):
    __tablename__ = "favorites"
    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    appid = Column(Integer, ForeignKey("releases.appid"), primary_key=True)

    user = relationship("User", back_populates="favorites")
    release = relationship("Release", back_populates="favorites")

class Release(Base):
    __tablename__ = "releases"

    appid = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    release_date = Column(String, nullable=True)
    release_date_checked = Column(Boolean, default=False)
    type = Column(String, nullable=True)
    genres = Column(String, nullable=True)
    updated_at = Column(String, nullable=True)  # ISO-строка с датой и временем
    unavailable = Column(Boolean, default=False)

    favorites = relationship("Favorite", back_populates="release", cascade="all, delete")

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True)
    hashed_password = Column(String)
    games = relationship("Game", back_populates="user")  # 👈 связь с играми
    achievements = relationship("Achievement", back_populates="user")  # 👈 связь с ачивками
    favorites = relationship("Favorite", back_populates="user", cascade="all, delete")

class Game(Base):
    __tablename__ = "games"
    id = Column(Integer, primary_key=True, index=True)
    appid = Column(Integer, nullable=False)
    name = Column(String, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    achievements = relationship("Achievement", back_populates="game")
    user = relationship("User", back_populates="games")  # 👈 связь с пользователем

class Achievement(Base):
    __tablename__ = "achievements"
    id = Column(Integer, primary_key=True, index=True)
    appid = Column(Integer, ForeignKey("games.appid"), nullable=False)
    name = Column(String, nullable=False)
    displayname = Column(String, nullable=False)
    defaultval = Column(Integer, default=0)
    hidden = Column(Integer, default=0)
    icon = Column(String)
    icongray = Column(String)
    obtained_date = Column(DateTime, default=None, nullable=True)
    game = relationship("Game", back_populates="achievements")
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    user = relationship("User", back_populates="achievements")  # 👈 связь с пользователем

    @property
    def earned(self):
        # Проверка, что дата получения не равна None или '0000-00-00'
        return self.obtained_date is not None and self.obtained_date != '0000-00-00'

class PushSubscription(Base):
    __tablename__ = "push_subscriptions"
    id = Column(Integer, primary_key=True, index=True)
    endpoint = Column(String, nullable=False)
    p256dh = Column(String, nullable=False)
    auth = Column(String, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    user = relationship("User")


class PushSubscriptionCreate(BaseModel):
    endpoint: str
    p256dh: str
    auth: str

class SubscriptionCheckRequest(BaseModel):
    endpoint: str


class AchievementData(BaseModel):
    appid: int
    achievement_name: str
    obtained_time: int
    user_id: int