from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings as app_settings
from models import Download, DownloadStatus, XtreamAccount, AppSettings
from services.xtream_client import XtreamClient
from services.file_namer import file_namer
from services.vod_namer import movie_output_path, series_episode_output_path


def _resolve_download_folder(settings: Optional[AppSettings]) -> str:
    if settings and settings.download_folder:
        return settings.download_folder
    return app_settings.default_download_folder


def _extract_year(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    return file_namer.extract_year(text)


async def build_movie_download(
    session: AsyncSession,
    account_id: int,
    vod_id: str,
    title: str,
    container_extension: Optional[str],
    direct_source: Optional[str] = None,
    release_date: Optional[str] = None,
) -> Download:
    result = await session.execute(select(XtreamAccount).where(XtreamAccount.id == account_id))
    account = result.scalar_one_or_none()
    if not account:
        raise ValueError("Account not found")

    settings_result = await session.execute(select(AppSettings))
    settings = settings_result.scalar_one_or_none()
    download_folder = _resolve_download_folder(settings)

    year = _extract_year(release_date) or _extract_year(title)
    output_path = movie_output_path(download_folder, title, year, container_extension)

    if direct_source:
        source_url = direct_source
    else:
        client = XtreamClient(account.server_url, account.username, account.password)
        source_url = client.build_vod_url(vod_id, container_extension)

    now = datetime.utcnow()

    return Download(
        account_id=account_id,
        channel_id=str(vod_id),
        channel_name="On Demand Movies",
        program_title=title or "Unknown",
        program_start=now,
        program_end=now,
        duration_minutes=0,
        source_url=source_url,
        output_path=output_path,
        status=DownloadStatus.PENDING.value,
        is_vod=True,
    )


async def build_episode_download(
    session: AsyncSession,
    account_id: int,
    series_id: str,
    show_name: str,
    episode_id: str,
    season: int,
    episode_num: int,
    episode_title: Optional[str],
    container_extension: Optional[str],
    direct_source: Optional[str] = None,
    duration_minutes: Optional[int] = None,
) -> Download:
    result = await session.execute(select(XtreamAccount).where(XtreamAccount.id == account_id))
    account = result.scalar_one_or_none()
    if not account:
        raise ValueError("Account not found")

    settings_result = await session.execute(select(AppSettings))
    settings = settings_result.scalar_one_or_none()
    download_folder = _resolve_download_folder(settings)

    output_path = series_episode_output_path(
        download_folder,
        show_name,
        season,
        episode_num,
        episode_title,
        container_extension,
    )

    if direct_source:
        source_url = direct_source
    else:
        client = XtreamClient(account.server_url, account.username, account.password)
        source_url = client.build_series_url(episode_id, container_extension)

    now = datetime.utcnow()

    return Download(
        account_id=account_id,
        channel_id=str(series_id),
        channel_name="On Demand Shows",
        program_title=episode_title or show_name or "Unknown",
        program_start=now,
        program_end=now,
        duration_minutes=int(duration_minutes or 0),
        source_url=source_url,
        output_path=output_path,
        status=DownloadStatus.PENDING.value,
        is_vod=True,
    )
