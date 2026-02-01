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
        from sqlalchemy import select, text
        from models import AppSettings
        from config import settings as app_settings

        # Add new columns if missing (SQLite)
        async with engine.begin() as conn:
            try:
                result = await conn.execute(text("PRAGMA table_info(app_settings)"))
                rows = result.fetchall()
                existing = {row[1] for row in rows}
                required_columns = {
                    "download_folder": "VARCHAR(1000) NOT NULL DEFAULT './data/downloads'",
                    "tv_template": "VARCHAR(500) NOT NULL DEFAULT '{show} - S{season:02d}E{episode:02d} - {title}'",
                    "movie_template": "VARCHAR(500) NOT NULL DEFAULT '{title} ({year})'",
                    "sports_template": "VARCHAR(500) NOT NULL DEFAULT '{title} - {date}'",
                    "default_template": "VARCHAR(500) NOT NULL DEFAULT '{channel} - {title} - {date}'",
                    "max_concurrent_downloads": "INTEGER NOT NULL DEFAULT 2",
                    "transcode_enabled": "BOOLEAN NOT NULL DEFAULT 1",
                    "transcode_format": "VARCHAR(10) NOT NULL DEFAULT 'mkv'",
                    "hw_accel": "VARCHAR(20) NOT NULL DEFAULT 'cpu'",
                    "transcode_quality": "VARCHAR(20) NOT NULL DEFAULT 'balanced'",
                    "delete_original_after_transcode": "BOOLEAN NOT NULL DEFAULT 1",
                    "remux_only": "BOOLEAN NOT NULL DEFAULT 1",
                    "epg_offset_minutes": "INTEGER NOT NULL DEFAULT 0",
                    "comskip_enabled": "BOOLEAN NOT NULL DEFAULT 0",
                    "comskip_path": "VARCHAR(1000)",
                    "comskip_ini_path": "VARCHAR(1000)",
                    "remove_commercials": "BOOLEAN NOT NULL DEFAULT 1",
                    "show_future_programs": "BOOLEAN NOT NULL DEFAULT 0",
                }
                for column, column_def in required_columns.items():
                    if column not in existing:
                        await conn.execute(
                            text(f"ALTER TABLE app_settings ADD COLUMN {column} {column_def}")
                        )
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
