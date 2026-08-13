from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Annotated, Optional
import logging
import os

from auth import require_admin_or_download_user, AuthContext
from database import get_session
from models import AppSettings, Download, DownloadStatus, XtreamAccount
from services.account_credentials import resolve_account_password_with_migration
from services.disk_space import check_disk_space
from services.xtream_client import XtreamClient
from services.vod_service import build_movie_download, build_episode_download
from services.download_manager import download_manager


router = APIRouter()
logger = logging.getLogger(__name__)


class MovieDownloadRequest(BaseModel):
    account_id: int
    vod_id: str
    name: str
    container_extension: Optional[str] = None
    direct_source: Optional[str] = None
    release_date: Optional[str] = None


class EpisodeItem(BaseModel):
    id: str
    season: int
    episode_num: int
    title: Optional[str] = None
    container_extension: Optional[str] = None
    direct_source: Optional[str] = None
    duration_minutes: Optional[int] = None


class SeriesDownloadRequest(BaseModel):
    account_id: int
    series_id: str
    series_name: str
    episodes: Annotated[list[EpisodeItem], Field(max_length=200)]


class ExternalVODDownloadRequest(BaseModel):
    """Trusted integration request for an already-resolved VOD source.

    The caller supplies the exact provider URL plus a path relative to Mustarrd's
    configured downloads root. DownloadManager then preserves that relative path
    when it moves the completed file into the completed root.
    """

    account_id: int
    media_id: str = Field(min_length=1, max_length=255)
    title: str = Field(min_length=1, max_length=500)
    source_url: str = Field(min_length=1, max_length=8192)
    relative_output_path: str = Field(min_length=1, max_length=900)
    duration_minutes: int = Field(default=0, ge=0, le=100000)


async def _get_client(session: AsyncSession, account: XtreamAccount) -> XtreamClient:
    password = await resolve_account_password_with_migration(session, account)
    return XtreamClient(account.server_url, account.username, password)


async def _get_account(session: AsyncSession, account_id: int) -> XtreamAccount:
    result = await session.execute(
        select(XtreamAccount).where(XtreamAccount.id == account_id)
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return account


def _validate_external_source_url(source_url: str) -> str:
    """Accept only an absolute HTTP(S) URL for trusted integration downloads."""
    try:
        parsed = urlparse(source_url)
    except Exception as exc:
        raise ValueError("Invalid source URL") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("source_url must be an absolute HTTP(S) URL")
    return source_url


def _external_output_path(download_folder: str, relative_output_path: str) -> str:
    """Resolve a caller-supplied relative path without allowing root escape."""
    raw = str(relative_output_path or "").strip()
    if not raw or "\x00" in raw:
        raise ValueError("Invalid output path")

    # Treat backslashes as separators too so a Windows-style traversal string
    # cannot bypass validation when Mustarrd runs on Linux.
    normalized = raw.replace("\\", "/")
    relative = Path(normalized)
    if relative.is_absolute() or any(part == ".." for part in relative.parts):
        raise ValueError("Output path must remain relative to the downloads folder")

    parts = [part for part in relative.parts if part not in {"", "."}]
    if not parts:
        raise ValueError("Invalid output path")

    root = Path(download_folder).expanduser().resolve()
    target = root.joinpath(*parts).resolve(strict=False)
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError("Output path escapes the downloads folder") from exc

    if len(str(target)) > 1000:
        raise ValueError("Output path is too long")
    return str(target)


@router.post("/external/download")
async def download_external_vod(
    data: ExternalVODDownloadRequest,
    auth: AuthContext = Depends(require_admin_or_download_user),
    session: AsyncSession = Depends(get_session),
):
    """Queue a VOD URL selected by a trusted local integration.

    Local credential users and admins may use this endpoint. Plex-authenticated
    download-only users intentionally cannot submit arbitrary external URLs.
    """
    if not auth.is_admin and auth.provider != "local":
        raise HTTPException(status_code=403, detail="Local integration access required")

    await _get_account(session, data.account_id)

    try:
        source_url = _validate_external_source_url(data.source_url)
        settings_result = await session.execute(select(AppSettings))
        settings_row = settings_result.scalar_one_or_none()
        # Use the same effective-folder resolution as DownloadManager so Docker
        # path fallbacks cannot cause the requested relative tree to be flattened
        # when the file is later moved into the completed root.
        download_folder = download_manager._resolve_download_folder(settings_row)
        output_path = _external_output_path(download_folder, data.relative_output_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    now = datetime.utcnow()
    download = Download(
        account_id=data.account_id,
        channel_id=data.media_id,
        channel_name="External VOD",
        program_title=data.title,
        program_start=now,
        program_end=now,
        duration_minutes=data.duration_minutes,
        source_url=source_url,
        output_path=output_path,
        status=DownloadStatus.PENDING.value,
        is_vod=True,
        requested_by_user_id=auth.user_id,
        request_source="external_vod",
    )

    await check_disk_space(session)
    try:
        download = await download_manager.queue_download(download)
    except ValueError:
        raise HTTPException(status_code=409, detail="A download for this output path is already active.")
    return download.to_dict()


@router.get("/movies/categories")
async def get_movie_categories(
    account_id: int,
    _auth: AuthContext = Depends(require_admin_or_download_user),
    session: AsyncSession = Depends(get_session)
):
    account = await _get_account(session, account_id)
    client = await _get_client(session, account)
    try:
        return await client.get_vod_categories()
    except Exception:
        logger.exception("Failed to load VOD categories account_id=%s", account_id)
        raise HTTPException(status_code=400, detail="Failed to load VOD categories from provider")
    finally:
        await client.close()


@router.get("/movies")
async def get_movies(
    account_id: int,
    category_id: Optional[str] = None,
    _auth: AuthContext = Depends(require_admin_or_download_user),
    session: AsyncSession = Depends(get_session)
):
    account = await _get_account(session, account_id)
    client = await _get_client(session, account)
    try:
        return await client.get_vod_streams(category_id)
    except Exception:
        logger.exception(
            "Failed to load VOD streams account_id=%s category_id=%s",
            account_id,
            category_id,
        )
        raise HTTPException(status_code=400, detail="Failed to load VOD content from provider")
    finally:
        await client.close()


@router.get("/movies/{vod_id}")
async def get_movie_info(
    vod_id: str,
    account_id: int,
    _auth: AuthContext = Depends(require_admin_or_download_user),
    session: AsyncSession = Depends(get_session)
):
    account = await _get_account(session, account_id)
    client = await _get_client(session, account)
    try:
        return await client.get_vod_info(vod_id)
    except Exception:
        logger.exception("Failed to load VOD info account_id=%s vod_id=%s", account_id, vod_id)
        raise HTTPException(status_code=400, detail="Failed to load VOD details from provider")
    finally:
        await client.close()


@router.post("/movies/download")
async def download_movie(
    data: MovieDownloadRequest,
    auth: AuthContext = Depends(require_admin_or_download_user),
    session: AsyncSession = Depends(get_session)
):
    try:
        download = await build_movie_download(
            session,
            account_id=data.account_id,
            vod_id=data.vod_id,
            title=data.name,
            container_extension=data.container_extension,
            direct_source=data.direct_source,
            release_date=data.release_date,
            requested_by_user_id=auth.user_id,
            request_source=auth.provider or "admin_local",
        )
    except ValueError as exc:
        logger.exception(
            "Failed to queue movie download account_id=%s vod_id=%s",
            data.account_id,
            data.vod_id,
        )
        message = str(exc)
        if "Account not found" in message:
            raise HTTPException(status_code=404, detail="Account not found")
        raise HTTPException(status_code=400, detail="Unable to queue movie download")

    await check_disk_space(session)
    try:
        download = await download_manager.queue_download(download)
    except ValueError:
        raise HTTPException(status_code=409, detail="A download for this file is already active.")
    return download.to_dict()


@router.get("/series/categories")
async def get_series_categories(
    account_id: int,
    _auth: AuthContext = Depends(require_admin_or_download_user),
    session: AsyncSession = Depends(get_session)
):
    account = await _get_account(session, account_id)
    client = await _get_client(session, account)
    try:
        return await client.get_series_categories()
    except Exception:
        logger.exception("Failed to load series categories account_id=%s", account_id)
        raise HTTPException(status_code=400, detail="Failed to load series categories from provider")
    finally:
        await client.close()


@router.get("/series")
async def get_series(
    account_id: int,
    category_id: Optional[str] = None,
    _auth: AuthContext = Depends(require_admin_or_download_user),
    session: AsyncSession = Depends(get_session)
):
    account = await _get_account(session, account_id)
    client = await _get_client(session, account)
    try:
        return await client.get_series(category_id)
    except Exception:
        logger.exception(
            "Failed to load series account_id=%s category_id=%s",
            account_id,
            category_id,
        )
        raise HTTPException(status_code=400, detail="Failed to load series from provider")
    finally:
        await client.close()


@router.get("/series/{series_id}")
async def get_series_info(
    series_id: str,
    account_id: int,
    _auth: AuthContext = Depends(require_admin_or_download_user),
    session: AsyncSession = Depends(get_session)
):
    account = await _get_account(session, account_id)
    client = await _get_client(session, account)
    try:
        return await client.get_series_info(series_id)
    except Exception:
        logger.exception("Failed to load series info account_id=%s series_id=%s", account_id, series_id)
        raise HTTPException(status_code=400, detail="Failed to load series details from provider")
    finally:
        await client.close()


@router.post("/series/download")
async def download_series(
    data: SeriesDownloadRequest,
    auth: AuthContext = Depends(require_admin_or_download_user),
    session: AsyncSession = Depends(get_session)
):
    # Build every episode first; nothing is persisted until the whole batch
    # validates, so a mid-batch failure cannot leave a partial episode set.
    downloads = []
    for episode in data.episodes:
        try:
            download = await build_episode_download(
                session,
                account_id=data.account_id,
                series_id=data.series_id,
                show_name=data.series_name,
                episode_id=episode.id,
                season=episode.season,
                episode_num=episode.episode_num,
                episode_title=episode.title,
                container_extension=episode.container_extension,
                direct_source=episode.direct_source,
                duration_minutes=episode.duration_minutes,
                requested_by_user_id=auth.user_id,
                request_source=auth.provider or "admin_local",
            )
        except ValueError as exc:
            logger.exception(
                "Failed to queue series episode download account_id=%s series_id=%s episode_id=%s",
                data.account_id,
                data.series_id,
                episode.id,
            )
            message = str(exc)
            if "Account not found" in message:
                raise HTTPException(status_code=404, detail="Account not found")
            raise HTTPException(status_code=400, detail="Unable to queue series download")
        downloads.append(download)

    if not downloads:
        return {"count": 0, "downloads": []}

    await check_disk_space(session)

    # One IN query for the whole batch instead of one duplicate check per episode.
    paths = [d.output_path for d in downloads]
    conflicts = set(await download_manager.find_active_output_conflicts(session, paths))
    conflicts.update(path for path, n in Counter(paths).items() if n > 1)
    if conflicts:
        names = ", ".join(sorted(os.path.basename(str(path)) for path in conflicts))
        raise HTTPException(
            status_code=409,
            detail=f"A download is already active for: {names}",
        )

    # All-or-nothing: a single commit covers the whole batch, and the episodes
    # are only enqueued after that commit succeeds.
    for download in downloads:
        session.add(download)
    await session.commit()

    queued = []
    for download in downloads:
        await download_manager.enqueue_persisted(download)
        queued.append(download.to_dict())

    return {
        "count": len(queued),
        "downloads": queued,
    }
