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
