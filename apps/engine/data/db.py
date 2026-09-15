"""The async SQLAlchemy engine and session factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from engine.core.config import Data
from engine.core.types import ConfigError, OrgId, StoreError


def create_engine(data: Data) -> AsyncEngine:
    """An engine for ZIPY_DATA__DATABASE_URL. An empty URL is a ConfigError."""
    url = data.database_url.get_secret_value()
    if not url:
        raise ConfigError("data.database_url is empty; set ZIPY_DATA__DATABASE_URL in .env")
    try:
        return create_async_engine(url, pool_pre_ping=True)
    except (SQLAlchemyError, ModuleNotFoundError) as exc:
        raise ConfigError(f"data.database_url names no usable async driver: {exc}") from exc


def sessions(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """The session factory every repository takes."""
    return async_sessionmaker(engine, expire_on_commit=False)


def org_uuid(org_id: OrgId) -> UUID:
    """The UUID an org id holds. An id that is not a UUID is a StoreError."""
    try:
        return UUID(org_id)
    except ValueError as exc:
        raise StoreError(f"org_id is not a uuid: {org_id}") from exc


@asynccontextmanager
async def store_errors(action: str) -> AsyncIterator[None]:
    """Reports a database failure inside the block as a StoreError naming the action."""
    try:
        yield
    except SQLAlchemyError as exc:
        raise StoreError(f"{action} failed: {exc}") from exc
