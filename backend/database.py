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
        await conn.run_sync(_migrate_app_settings_schema)
        await conn.run_sync(_ensure_account_columns)
        await conn.run_sync(_ensure_download_columns)
        await conn.run_sync(_ensure_scheduled_columns)
        await conn.run_sync(_ensure_user_columns)
        await conn.run_sync(_ensure_plex_server_columns)
        await conn.run_sync(_ensure_identity_indexes)
        await conn.run_sync(_ensure_epg_program_indexes)


def _ensure_app_settings_columns(conn):
    inspector = inspect(conn)
    if "app_settings" not in inspector.get_table_names():
        return

    existing_columns = {col["name"] for col in inspector.get_columns("app_settings")}
    additions = {
        "default_pre_padding_minutes": "INTEGER DEFAULT 1",
        "default_post_padding_minutes": "INTEGER DEFAULT 5",
        "min_free_space_gb": "INTEGER DEFAULT 25",
        "launch_on_startup": "BOOLEAN DEFAULT 1",
        "max_concurrent_post_processing": "INTEGER DEFAULT 1",
        "admin_password_hash": "VARCHAR(500)",
        "admin_username_bootstrap_required": "BOOLEAN DEFAULT 0",
        "onboarding_dismissed": "BOOLEAN DEFAULT 0",
        "onboarding_processing_confirmed": "BOOLEAN DEFAULT 0",
        "onboarding_comskip_confirmed": "BOOLEAN DEFAULT 0",
        "onboarding_selected_profile": "VARCHAR(64)",
    }

    for column_name, column_def in additions.items():
        if column_name not in existing_columns:
            conn.exec_driver_sql(
                f"ALTER TABLE app_settings ADD COLUMN {column_name} {column_def}"
            )


def _migrate_app_settings_schema(conn):
    inspector = inspect(conn)
    if "app_settings" not in inspector.get_table_names():
        return

    existing_columns = {col["name"] for col in inspector.get_columns("app_settings")}
    removed_columns = {"remove_commercials", "transcode_quality"}
    if not removed_columns.intersection(existing_columns):
        return

    conn.exec_driver_sql(
        """
        CREATE TABLE app_settings_new (
            id INTEGER PRIMARY KEY,
            download_folder VARCHAR(1000),
            completed_folder VARCHAR(1000),
            tv_template VARCHAR(500) DEFAULT '{show} - S{season:02d}E{episode:02d} - {title}',
            movie_template VARCHAR(500) DEFAULT '{title} ({year})',
            sports_template VARCHAR(500) DEFAULT '{title} - {date}',
            default_template VARCHAR(500) DEFAULT '{title} - {date}',
            max_concurrent_downloads INTEGER DEFAULT 2,
            min_free_space_gb INTEGER DEFAULT 25,
            default_pre_padding_minutes INTEGER DEFAULT 1,
            default_post_padding_minutes INTEGER DEFAULT 5,
            max_concurrent_post_processing INTEGER DEFAULT 1,
            transcode_enabled BOOLEAN DEFAULT 1,
            transcode_format VARCHAR(10) DEFAULT 'mkv',
            hw_accel VARCHAR(20) DEFAULT 'cpu',
            delete_original_after_transcode BOOLEAN DEFAULT 1,
            remux_only BOOLEAN DEFAULT 1,
            epg_offset_minutes INTEGER DEFAULT 0,
            show_future_programs BOOLEAN DEFAULT 0,
            launch_on_startup BOOLEAN DEFAULT 1,
            comskip_enabled BOOLEAN DEFAULT 0,
            comskip_path VARCHAR(1000),
            comskip_ini_path VARCHAR(1000),
            admin_password_hash VARCHAR(500),
            admin_username_bootstrap_required BOOLEAN DEFAULT 0,
            onboarding_dismissed BOOLEAN DEFAULT 0,
            onboarding_processing_confirmed BOOLEAN DEFAULT 0,
            onboarding_comskip_confirmed BOOLEAN DEFAULT 0,
            onboarding_selected_profile VARCHAR(64)
        )
        """
    )

    keep_columns = [
        "id",
        "download_folder",
        "completed_folder",
        "tv_template",
        "movie_template",
        "sports_template",
        "default_template",
        "max_concurrent_downloads",
        "min_free_space_gb",
        "default_pre_padding_minutes",
        "default_post_padding_minutes",
        "max_concurrent_post_processing",
        "transcode_enabled",
        "transcode_format",
        "hw_accel",
        "delete_original_after_transcode",
        "remux_only",
        "epg_offset_minutes",
        "show_future_programs",
        "launch_on_startup",
        "comskip_enabled",
        "comskip_path",
        "comskip_ini_path",
        "admin_password_hash",
        "admin_username_bootstrap_required",
        "onboarding_dismissed",
        "onboarding_processing_confirmed",
        "onboarding_comskip_confirmed",
        "onboarding_selected_profile",
    ]
    copy_columns = [col for col in keep_columns if col in existing_columns]
    if copy_columns:
        columns_csv = ", ".join(copy_columns)
        conn.exec_driver_sql(
            f"INSERT INTO app_settings_new ({columns_csv}) "
            f"SELECT {columns_csv} FROM app_settings"
        )

    conn.exec_driver_sql("DROP TABLE app_settings")
    conn.exec_driver_sql("ALTER TABLE app_settings_new RENAME TO app_settings")


def _ensure_download_columns(conn):
    inspector = inspect(conn)
    if "downloads" not in inspector.get_table_names():
        return

    existing_columns = {col["name"] for col in inspector.get_columns("downloads")}
    additions = {
        "is_vod": "BOOLEAN DEFAULT 0",
        "requested_by_user_id": "INTEGER",
        "request_source": "VARCHAR(32) DEFAULT 'admin'",
    }

    for column_name, column_def in additions.items():
        if column_name not in existing_columns:
            conn.exec_driver_sql(
                f"ALTER TABLE downloads ADD COLUMN {column_name} {column_def}"
            )


def _ensure_scheduled_columns(conn):
    inspector = inspect(conn)
    if "scheduled_recordings" not in inspector.get_table_names():
        return

    existing_columns = {col["name"] for col in inspector.get_columns("scheduled_recordings")}
    additions = {
        "requested_by_user_id": "INTEGER",
        "request_source": "VARCHAR(32) DEFAULT 'admin'",
    }

    for column_name, column_def in additions.items():
        if column_name not in existing_columns:
            conn.exec_driver_sql(
                f"ALTER TABLE scheduled_recordings ADD COLUMN {column_name} {column_def}"
            )


def _ensure_user_columns(conn):
    inspector = inspect(conn)
    if "users" not in inspector.get_table_names():
        return

    existing_columns = {col["name"] for col in inspector.get_columns("users")}
    additions = {
        "show_future_programs": "BOOLEAN",
    }

    for column_name, column_def in additions.items():
        if column_name not in existing_columns:
            conn.exec_driver_sql(
                f"ALTER TABLE users ADD COLUMN {column_name} {column_def}"
            )


def _ensure_plex_server_columns(conn):
    inspector = inspect(conn)
    if "plex_servers" not in inspector.get_table_names():
        return

    existing_columns = {col["name"] for col in inspector.get_columns("plex_servers")}
    additions = {
        "access_token_encrypted": "TEXT",
        "resource_id": "VARCHAR(255)",
        "resource_name": "VARCHAR(255)",
    }

    for column_name, column_def in additions.items():
        if column_name not in existing_columns:
            conn.exec_driver_sql(
                f"ALTER TABLE plex_servers ADD COLUMN {column_name} {column_def}"
            )


def _ensure_identity_indexes(conn):
    inspector = inspect(conn)
    if "user_identities" not in inspector.get_table_names():
        return

    existing_indexes = {idx["name"] for idx in inspector.get_indexes("user_identities")}
    if "ux_user_identities_provider_subject" not in existing_indexes:
        conn.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_user_identities_provider_subject "
            "ON user_identities (provider, provider_subject)"
        )


def _ensure_account_columns(conn):
    inspector = inspect(conn)
    if "xtream_accounts" not in inspector.get_table_names():
        return

    existing_columns = {col["name"] for col in inspector.get_columns("xtream_accounts")}
    additions = {
        "last_epg_backfill_at": "DATETIME",
        "password_encrypted": "VARCHAR(2048)",
    }

    for column_name, column_def in additions.items():
        if column_name not in existing_columns:
            conn.exec_driver_sql(
                f"ALTER TABLE xtream_accounts ADD COLUMN {column_name} {column_def}"
            )


def _ensure_epg_program_indexes(conn):
    inspector = inspect(conn)
    if "epg_programs" not in inspector.get_table_names():
        return

    existing_indexes = {idx["name"] for idx in inspector.get_indexes("epg_programs")}
    if "ux_epg_programs_account_epg_id" not in existing_indexes:
        conn.exec_driver_sql(
            "DELETE FROM epg_programs WHERE rowid NOT IN ("
            "SELECT MIN(rowid) FROM epg_programs GROUP BY account_id, epg_id"
            ")"
        )
        conn.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_epg_programs_account_epg_id "
            "ON epg_programs (account_id, epg_id)"
        )


async def get_session() -> AsyncSession:
    async with async_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()
