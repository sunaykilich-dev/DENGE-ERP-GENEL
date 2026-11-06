import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

import app.models  # noqa: F401 — tüm modelleri metadata'ya kaydettirir
from alembic import context
from app.config import get_config
from app.db import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", get_config().database_url)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    # ERP'nin çekirdek kısıtı — "aynı cihaz için çakışan dönem olamaz" —
    # EXCLUDE USING gist (device_id WITH =, tstzrange(...) WITH &&) ile yazılır
    # ve bu btree_gist olmadan ifade edilemez. Migration'lardan ÖNCE kurulur ki
    # ilk şema migration'ı kısıtı doğrudan tanımlayabilsin.
    connection.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS btree_gist")
    # pg_trgm: unvan benzerlik araması. Göçte 44 montaj noktasından mükerrer
    # çiftleri bulmak ve arama kutusunda yazım hatasına tolerans için.
    connection.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
        # SQLAlchemy 2.0 asenkron bağlantısı, blok çıkışında AÇIK BİRAKILAN
        # transaction'ı geri alır. Alembic'in kendi commit'i sync katmanda
        # kaldığı için bu satır olmadan migration sessizce geri alınır:
        # "Running upgrade" yazar ama tek bir tablo oluşmaz.
        await connection.commit()
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
