import logging
from logging.config import fileConfig

from alembic import context

from runtime_config import (
    RuntimeConfigurationError,
    resolve_migration_database_config,
)


def _resolve_verified_migration_configuration():
    """Fail before importing models or initializing any database machinery."""
    try:
        return resolve_migration_database_config()
    except RuntimeConfigurationError as exc:
        raise RuntimeError(
            f"BaseLodge migration configuration error: {exc}"
        ) from exc


# This is the mandatory boundary for raw Alembic and Flask-Migrate commands.
# Both offline and online paths use this already-verified configuration.
migration_configuration = _resolve_verified_migration_configuration()

from sqlalchemy import engine_from_config, pool

from models import db


config = context.config
fileConfig(config.config_file_name)
logger = logging.getLogger("alembic.env")
target_metadata = db.metadata


def get_migration_url():
    return migration_configuration.database_url


def run_migrations_offline():
    """Run migrations without importing or initializing the Flask app."""
    context.configure(
        url=get_migration_url(),
        target_metadata=target_metadata,
        literal_binds=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    """Run migrations through the explicit migration-only database URL."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_migration_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    try:
        with connectable.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
            )

            with context.begin_transaction():
                context.run_migrations()
    finally:
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()