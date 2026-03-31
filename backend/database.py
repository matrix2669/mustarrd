from sqlalchemy import inspect, text
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
        await _apply_lightweight_migrations(conn)


async def _column_exists(conn, table_name: str, column_name: str) -> bool:
    def _check(sync_conn):
        inspector = inspect(sync_conn)
        return any(col["name"] == column_name for col in inspector.get_columns(table_name))

    return await conn.run_sync(_check)


async def _apply_lightweight_migrations(conn) -> None:
    # Keep startup-safe schema additions here for existing installations.
    if not await _column_exists(conn, "plex_servers", "connection_uri"):
        await conn.execute(text("ALTER TABLE plex_servers ADD COLUMN connection_uri VARCHAR(1000)"))

    if not await _column_exists(conn, "app_settings", "plex_outbound_policy"):
        await conn.execute(
            text(
                "ALTER TABLE app_settings "
                "ADD COLUMN plex_outbound_policy VARCHAR(64) DEFAULT 'resource_connections_only'"
            )
        )

    if not await _column_exists(conn, "epg_programs", "provider_start"):
        await conn.execute(text("ALTER TABLE epg_programs ADD COLUMN provider_start VARCHAR(255)"))

    if not await _column_exists(conn, "epg_programs", "provider_stop"):
        await conn.execute(text("ALTER TABLE epg_programs ADD COLUMN provider_stop VARCHAR(255)"))

    if not await _column_exists(conn, "xtream_accounts", "catchup_resolution_mode"):
        await conn.execute(
            text("ALTER TABLE xtream_accounts ADD COLUMN catchup_resolution_mode VARCHAR(32) DEFAULT 'auto'")
        )

    if not await _column_exists(conn, "xtream_accounts", "catchup_fallback_offset_minutes"):
        await conn.execute(
            text("ALTER TABLE xtream_accounts ADD COLUMN catchup_fallback_offset_minutes INTEGER DEFAULT 0")
        )

    if not await _column_exists(conn, "scheduled_recordings", "provider_start"):
        await conn.execute(text("ALTER TABLE scheduled_recordings ADD COLUMN provider_start VARCHAR(255)"))

    if not await _column_exists(conn, "scheduled_recordings", "provider_stop"):
        await conn.execute(text("ALTER TABLE scheduled_recordings ADD COLUMN provider_stop VARCHAR(255)"))


async def get_session() -> AsyncSession:
    async with async_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()
