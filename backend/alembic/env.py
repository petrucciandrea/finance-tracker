"""
Alembic environment configuration.

Reads the DB URL from app settings (Pydantic Settings / .env) instead of a
hardcoded value in alembic.ini, and points target_metadata at the app's
declarative Base so `alembic revision --autogenerate` can diff against it.
"""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# --- App imports -----------------------------------------------------------
# Adjust these import paths to match your actual package layout.
from app.core.config import settings  # Pydantic BaseSettings with `database_url`
from app.models import Base

# ---------------------------------------------------------------------------

# Alembic Config object, gives access to values in alembic.ini
config = context.config

# Override the sqlalchemy.url from alembic.ini with the one from our app
# settings, so a single .env is the source of truth for the DB connection.
config.set_main_option("sqlalchemy.url", str(settings.database_url))

# Interpret the config file for Python logging (loggers defined in alembic.ini)
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Metadata used for 'autogenerate' support
target_metadata = Base.metadata


def include_object(object, name, type_, reflected, compare_to):
    """
    Filter objects considered by autogenerate.

    Useful later if you add extensions/tables managed outside SQLAlchemy
    (e.g. a Postgres extension table) that should never be auto-diffed.
    Currently includes everything.
    """
    return True


def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode.

    Configures the context with just a URL and not an Engine, though an
    Engine is acceptable here as well. By skipping the Engine creation we
    don't even need a DBAPI to be available. Calls to context.execute()
    emit the given string to the script output.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Run migrations in 'online' mode.

    Creates an Engine and associates a connection with the context, so
    migrations run directly against the live database.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()