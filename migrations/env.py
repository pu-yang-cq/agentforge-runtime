import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from agentforge.infrastructure.db.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# URL precedence is explicit and intentionally testable. Programmatic callers
# (notably the destructive integration-schema reset) may set an explicit URL
# through config.attributes; that value must never be silently replaced by an
# ambient application database URL. Normal CLI migrations may use
# AGENTFORGE_DATABASE_URL, while offline SQL falls back to alembic.ini.
explicit_database_url = config.attributes.get("agentforge_explicit_database_url")
database_url = explicit_database_url or os.getenv("AGENTFORGE_DATABASE_URL")
if database_url:
    config.set_main_option("sqlalchemy.url", str(database_url))


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
