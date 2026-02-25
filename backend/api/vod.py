from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional

from auth import require_admin_or_download_user, AuthContext
from database import get_session
from models import XtreamAccount
from services.account_credentials import resolve_account_password_with_migration
from services.xtream_client import XtreamClient
from services.vod_service import build_movie_download, build_episode_download
from services.download_manager import download_manager


router = APIRouter()


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
    episodes: list[EpisodeItem]


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
            requested_by_user_id=auth.user_id if not auth.is_admin else None,
            request_source=auth.provider if not auth.is_admin else "admin",
        )
    except ValueError as exc:
        message = str(exc)
        raise HTTPException(status_code=400, detail=message)

    download = await download_manager.queue_download(download)
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
    finally:
        await client.close()


@router.post("/series/download")
async def download_series(
    data: SeriesDownloadRequest,
    auth: AuthContext = Depends(require_admin_or_download_user),
    session: AsyncSession = Depends(get_session)
):
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
                requested_by_user_id=auth.user_id if not auth.is_admin else None,
                request_source=auth.provider if not auth.is_admin else "admin",
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        download = await download_manager.queue_download(download)
        downloads.append(download.to_dict())

    return {
        "count": len(downloads),
        "downloads": downloads,
    }
