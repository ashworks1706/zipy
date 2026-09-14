"""Alembic environment: the URL from the engine config, the metadata from engine.data.tables."""

import asyncio

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from engine.core.config import load
from engine.data.tables import Base

target_metadata = Base.metadata


def run_migrations_offline():
    """Emit SQL without a connection."""
    context.configure(
        url=load().data.database_url.get_secret_value(),
        target_metadata=target_metadata,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online():
    """Run migrations over an async connection."""
    engine = create_async_engine(load().data.database_url.get_secret_value())
    async with engine.connect() as connection:
        await connection.run_sync(_run)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
