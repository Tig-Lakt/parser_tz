from contextlib import contextmanager, asynccontextmanager
from typing import Generator, AsyncGenerator

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import Session, sessionmaker

from config import settings
from db.models import Base


# Sync engine (для Alembic и migrations)
sync_engine = create_engine(
    settings.database_url,
    echo=settings.db_echo,
    pool_pre_ping=True, 
    pool_size=5,
    max_overflow=10,
)

SyncSessionLocal = sessionmaker(
    bind=sync_engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


# Async engine (для парсера)
async_engine = create_async_engine(
    settings.async_database_url,
    echo=settings.db_echo,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)

AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


# Context managers
@contextmanager
def get_sync_session() -> Generator[Session, None, None]:
    """Синхронная сессия — для Selenium части (kad.arbitr.ru)."""
    session = SyncSessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

# DB init
def init_db() -> None:
    """Создаёт все таблицы если они не существуют."""
    Base.metadata.create_all(bind=sync_engine)