from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
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

    # One-time migration: ensure download_folder defaults to config setting
    try:
        from sqlalchemy import select
        from models import AppSettings
        from config import settings as app_settings

        # Add new columns if missing (SQLite)
        async with engine.begin() as conn:
            try:
                result = await conn.execute("PRAGMA table_info(app_settings)")
                rows = result.fetchall()
                existing = {row[1] for row in rows}
                if "remux_only" not in existing:
                    await conn.execute("ALTER TABLE app_settings ADD COLUMN remux_only BOOLEAN NOT NULL DEFAULT 1")
                if "epg_offset_minutes" not in existing:
                    await conn.execute("ALTER TABLE app_settings ADD COLUMN epg_offset_minutes INTEGER NOT NULL DEFAULT 0")
            except Exception:
                pass

        async with async_session_maker() as session:
            result = await session.execute(select(AppSettings))
            settings = result.scalar_one_or_none()
            if settings and (not settings.download_folder or settings.download_folder.startswith("./data")):
                settings.download_folder = app_settings.default_download_folder
                session.add(settings)
                await session.commit()
    except Exception:
        # Best-effort migration; don't block startup
        pass


async def get_session() -> AsyncSession:
    async with async_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()
