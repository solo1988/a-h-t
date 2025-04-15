# models.py
from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from database import Base
import datetime
from pydantic import BaseModel

class Game(Base):
    __tablename__ = "games"
    id = Column(Integer, primary_key=True, index=True)
    appid = Column(Integer, unique=True, nullable=False)
    name = Column(String, nullable=False)
    achievements = relationship("Achievement", back_populates="game")

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


class PushSubscriptionCreate(BaseModel):
    endpoint: str
    p256dh: str
    auth: str
