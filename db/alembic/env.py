"""Alembic environment configuration for pf9-mngt.

Reads DB connection parameters from the same environment variables
used by the API and worker services so that the same credentials work
in both Docker-compose (local dev) and Kubernetes (production).

Supported env vars (all optional — fall back to local-dev defaults):
  DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
"""
import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

# ── Alembic Config object (gives access to alembic.ini values) ──
config = context.config

# ── Set up Python logging from the ini file ──
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ── Build the DB URL from env vars ──
db_host = os.getenv("DB_HOST", "localhost")
db_port = os.getenv("DB_PORT", "5432")
db_name = os.getenv("DB_NAME", "pf9_mgmt")
db_user = os.getenv("DB_USER", "pf9")
db_password = os.getenv("DB_PASSWORD", "")

_sqlalchemy_url = (
    f"postgresql+psycopg2://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
)
config.set_main_option("sqlalchemy.url", _sqlalchemy_url)

# No declarative metadata — we use raw SQL in each revision.
target_metadata = None


def run_migrations_offline() -> None:
    """Run migrations without a live DB connection (emit SQL to stdout)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live DB connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
