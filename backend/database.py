from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import inspect
from config import settings


class Base(DeclarativeBase):
    pass


engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_app_settings_columns)
        await conn.run_sync(_ensure_download_columns)


def _ensure_app_settings_columns(conn):
    inspector = inspect(conn)
    if "app_settings" not in inspector.get_table_names():
        return

    existing_columns = {col["name"] for col in inspector.get_columns("app_settings")}
    additions = {
        "default_pre_padding_minutes": "INTEGER DEFAULT 1",
        "default_post_padding_minutes": "INTEGER DEFAULT 5",
        "min_free_space_gb": "INTEGER DEFAULT 25",
    }

    for column_name, column_def in additions.items():
        if column_name not in existing_columns:
            conn.exec_driver_sql(
                f"ALTER TABLE app_settings ADD COLUMN {column_name} {column_def}"
            )


def _ensure_download_columns(conn):
    inspector = inspect(conn)
    if "downloads" not in inspector.get_table_names():
        return

    existing_columns = {col["name"] for col in inspector.get_columns("downloads")}
    additions = {
        "is_vod": "BOOLEAN DEFAULT 0",
    }

    for column_name, column_def in additions.items():
        if column_name not in existing_columns:
            conn.exec_driver_sql(
                f"ALTER TABLE downloads ADD COLUMN {column_name} {column_def}"
            )


async def get_session() -> AsyncSession:
    async with async_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()
