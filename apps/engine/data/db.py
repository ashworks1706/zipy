"""The async SQLAlchemy engine and session factory."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from engine.core.config import Data


def create_engine(data: Data) -> AsyncEngine:
    """An engine for ZIPY_DATA__DATABASE_URL. An empty URL is a ConfigError."""
    raise NotImplementedError


def sessions(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """The session factory every repository takes."""
    return async_sessionmaker(engine, expire_on_commit=False)
