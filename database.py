# database.py
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import create_engine

# Асинхронный движок и сессия (для FastAPI и async функций)
ASYNC_DATABASE_URL = "sqlite+aiosqlite:///./games.db"
async_engine = create_async_engine(ASYNC_DATABASE_URL, echo=False)
SessionLocal = sessionmaker(bind=async_engine, class_=AsyncSession, expire_on_commit=False)

# Синхронный движок и сессия (для фоновых задач и sync-функций)
SYNC_DATABASE_URL = "sqlite:///./games.db"
sync_engine = create_engine(SYNC_DATABASE_URL, connect_args={"check_same_thread": False})
SyncSessionLocal = sessionmaker(bind=sync_engine, autocommit=False, autoflush=False)

Base = declarative_base()

async def init_db():
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
