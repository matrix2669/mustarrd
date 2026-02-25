from datetime import datetime, timedelta
from typing import Optional
import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Download, DownloadStatus, AppSettings, XtreamAccount
from services.account_credentials import resolve_account_password_with_migration
from services.file_namer import file_namer
from services.epg_service import epg_service
from services.xtream_client import XtreamClient
from config import settings as app_settings


def _parse_program_times(program: dict) -> tuple[datetime, datetime, int, datetime, datetime]:
    start_timestamp = program.get("start_timestamp")
    stop_timestamp = program.get("stop_timestamp")

    if start_timestamp and stop_timestamp:
        program_start_utc = datetime.utcfromtimestamp(int(start_timestamp))
        program_end_utc = datetime.utcfromtimestamp(int(stop_timestamp))
        duration_minutes = int((program_end_utc - program_start_utc).total_seconds() / 60)
    else:
        program_start_utc = datetime.fromisoformat(program["start_time"])
        program_end_utc = datetime.fromisoformat(program["end_time"])
        duration_minutes = int((program_end_utc - program_start_utc).total_seconds() / 60)

    if program.get("start_time") and program.get("end_time"):
        program_start_local = datetime.fromisoformat(program["start_time"])
        program_end_local = datetime.fromisoformat(program["end_time"])
    else:
        program_start_local = program_start_utc
        program_end_local = program_end_utc

    return program_start_utc, program_end_utc, duration_minutes, program_start_local, program_end_local


async def build_download_from_program(
    session: AsyncSession,
    account_id: int,
    channel_id: str,
    channel_name: str,
    program: dict,
    custom_filename: Optional[str] = None,
    pre_padding_minutes: int = 0,
    post_padding_minutes: int = 0,
    requested_by_user_id: Optional[int] = None,
    request_source: str = "admin",
) -> Download:
    result = await session.execute(
        select(XtreamAccount).where(XtreamAccount.id == account_id)
    )
    account = result.scalar_one_or_none()

    if not account:
        raise ValueError("Account not found")

    settings_result = await session.execute(select(AppSettings))
    settings = settings_result.scalar_one_or_none()
    download_folder = settings.download_folder if settings and settings.download_folder else app_settings.default_download_folder

    program_start_utc, program_end_utc, duration_minutes, program_start, program_end = _parse_program_times(program)

    if duration_minutes <= 0:
        raise ValueError("Invalid program duration")

    channel = {
        "name": channel_name,
        "stream_id": channel_id,
        "category_name": program.get("category", ""),
    }

    if custom_filename:
        filename = custom_filename
        if not filename.endswith(".ts"):
            filename += ".ts"
        filename = file_namer.sanitize_filename(filename.replace(".ts", "")) + ".ts"
    else:
        program_type = epg_service.detect_program_type(program, channel)
        filename = file_namer.generate_filename(program, channel, program_type)

    pre_padding = int(pre_padding_minutes or 0)
    post_padding = int(post_padding_minutes or 0)
    padded_start_utc = program_start_utc
    padded_duration = duration_minutes
    if pre_padding:
        padded_start_utc = program_start_utc - timedelta(minutes=pre_padding)
        padded_duration += pre_padding
    if post_padding:
        padded_duration += post_padding

    password = await resolve_account_password_with_migration(session, account)
    client = XtreamClient(account.server_url, account.username, password)
    source_url = client.build_timeshift_url(channel_id, padded_start_utc, padded_duration)

    return Download(
        account_id=account_id,
        channel_id=channel_id,
        channel_name=channel_name,
        program_title=program.get("title", "Unknown"),
        program_start=program_start,
        program_end=program_end,
        duration_minutes=padded_duration,
        source_url=source_url,
        output_path=os.path.join(download_folder, filename),
        status=DownloadStatus.PENDING.value,
        requested_by_user_id=requested_by_user_id,
        request_source=request_source,
    )
