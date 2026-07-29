"""Alembic environment for REAL TRADING BOT.

Skema-kilden er ``core.database.Base`` (samme metadata som ``create_all`` bruger),
og URL'en tages fra ``core.database.SYNC_DATABASE_URL`` — så migrationer altid rammer
den samme SQLite-fil som resten af projektet. En anden database kan tvinges ad-hoc med
``-x dburl=sqlite:///andet.db`` (bruges til autogenerering mod en tom temp-DB og til at
verificere ``upgrade head`` på en frisk fil uden at røre produktions-DB'en).

SQLite kan ikke ALTER de fleste kolonner in-place; ``render_as_batch=True`` får Alembic
til at generere batch-migrationer (kopiér-tabel-mønsteret), så fremtidige kolonneændringer
virker — præcis det ``_apply_additive_migrations`` løste manuelt før.
"""

import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# Gør projekt-roden importerbar (alembic køres fra rod, men vær eksplicit).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import SYNC_DATABASE_URL, Base  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _db_url() -> str:
    """URL-prioritet: -x dburl=... > alembic.ini > core.database.SYNC_DATABASE_URL."""
    x_args = context.get_x_argument(as_dictionary=True)
    if x_args.get("dburl"):
        return x_args["dburl"]
    return config.get_main_option("sqlalchemy.url") or SYNC_DATABASE_URL


def run_migrations_offline() -> None:
    context.configure(
        url=_db_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _db_url()
    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
