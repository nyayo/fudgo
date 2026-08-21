"""Alembic async environment.

Uses ``connection.run_sync()`` — the standard SQLAlchemy 2.0 async-migration
pattern. The DB URL comes from ``app.core.config.get_settings()`` (asyncpg).
``target_metadata`` is ``SQLModel.metadata`` (empty in Phase 0; later phases
import their models in ``app/db/base.py`` so autogenerate can see them).
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel

from app.core.config import get_settings

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

target_metadata = SQLModel.metadata


def include_object(object, name, type_, reflected, compare_to):  # type: ignore[no-untyped-def]
    """Compare everything (no exclusions) when autogenerating."""
    return True


def run_migrations_offline() -> None:
    """Generate script files without a live DB connection."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_name="postgresql",
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live async engine."""

    async def migrate() -> None:
        engine = create_async_engine(config.get_main_option("sqlalchemy.url"))
        async with engine.connect() as connection:
            connection = connection

            def do_run(connection):  # type: ignore[no-untyped-def]
                context.configure(
                    connection=connection,
                    target_metadata=target_metadata,
                    include_object=include_object,
                )
                with context.begin_transaction():
                    context.run_migrations()

            await connection.run_sync(do_run)
        await engine.dispose()

    asyncio.run(migrate())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
