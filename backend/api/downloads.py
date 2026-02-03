from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, conint
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional
import os

from database import get_session, async_session_maker
from models import Download, DownloadStatus, XtreamAccount, AppSettings
from services.download_manager import download_manager
from services.xtream_client import XtreamClient
from services.file_namer import file_namer
from services.epg_service import epg_service
from config import settings as app_settings


router = APIRouter()


class DownloadCreate(BaseModel):
    account_id: int
    channel_id: str
    channel_name: str
    program: dict  # EPG program data
    custom_filename: Optional[str] = None
    pre_padding_minutes: Optional[conint(ge=0)] = 0
    post_padding_minutes: Optional[conint(ge=0)] = 0


class FilenamePreview(BaseModel):
    account_id: int
    channel_id: str
    channel_name: str
    program: dict


@router.get("")
async def list_downloads(session: AsyncSession = Depends(get_session)):
    """List all downloads (queue + history)."""
    result = await session.execute(
        select(Download).order_by(Download.created_at.desc())
    )
    downloads = result.scalars().all()
    return [download_manager.merge_progress_snapshot(d.to_dict()) for d in downloads]


@router.get("/queue")
async def get_download_queue():
    """Get pending and active downloads."""
    return await download_manager.get_queue()


@router.get("/history")
async def get_download_history():
    """Get completed, failed, and cancelled downloads."""
    return await download_manager.get_history()


@router.post("/preview-filename")
async def preview_filename(
    data: FilenamePreview,
    session: AsyncSession = Depends(get_session)
):
    """Preview the auto-generated filename for a program."""
    # Get channel info for type detection
    result = await session.execute(
        select(XtreamAccount).where(XtreamAccount.id == data.account_id)
    )
    account = result.scalar_one_or_none()

    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    # Build channel dict for file namer
    channel = {
        "name": data.channel_name,
        "stream_id": data.channel_id,
        "category_name": data.program.get("category", ""),
    }

    # Detect program type
    program_type = epg_service.detect_program_type(data.program, channel)

    # Generate filename
    filename = file_namer.generate_filename(data.program, channel, program_type)

    return {
        "filename": filename,
        "detected_type": program_type,
    }


@router.post("")
async def create_download(
    data: DownloadCreate,
    session: AsyncSession = Depends(get_session)
):
    """Queue a new download."""
    # Get account
    result = await session.execute(
        select(XtreamAccount).where(XtreamAccount.id == data.account_id)
    )
    account = result.scalar_one_or_none()

    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    # Get settings for download folder
    settings_result = await session.execute(select(AppSettings))
    settings = settings_result.scalar_one_or_none()
    if settings and settings.download_folder and not settings.download_folder.startswith("./data"):
        download_folder = settings.download_folder
    else:
        download_folder = app_settings.default_download_folder

    # Parse program times - use UTC timestamps for timeshift URL
    start_timestamp = data.program.get("start_timestamp")
    stop_timestamp = data.program.get("stop_timestamp")

    if start_timestamp and stop_timestamp:
        # Use original UTC timestamps
        program_start_utc = datetime.utcfromtimestamp(int(start_timestamp))
        program_end_utc = datetime.utcfromtimestamp(int(stop_timestamp))
        duration_minutes = int((program_end_utc - program_start_utc).total_seconds() / 60)
    else:
        # Fallback to parsed times
        program_start_utc = datetime.fromisoformat(data.program["start_time"])
        program_end_utc = datetime.fromisoformat(data.program["end_time"])
        duration_minutes = int((program_end_utc - program_start_utc).total_seconds() / 60)

    # Keep local times for display/storage
    program_start = datetime.fromisoformat(data.program["start_time"])
    program_end = datetime.fromisoformat(data.program["end_time"])

    # Build channel dict
    channel = {
        "name": data.channel_name,
        "stream_id": data.channel_id,
        "category_name": data.program.get("category", ""),
    }

    # Generate filename
    if data.custom_filename:
        filename = data.custom_filename
        if not filename.endswith(".ts"):
            filename += ".ts"
        filename = file_namer.sanitize_filename(filename.replace(".ts", "")) + ".ts"
    else:
        program_type = epg_service.detect_program_type(data.program, channel)
        filename = file_namer.generate_filename(data.program, channel, program_type)

    if duration_minutes <= 0:
        raise HTTPException(status_code=400, detail="Invalid program duration")

    pre_padding = int(data.pre_padding_minutes or 0)
    post_padding = int(data.post_padding_minutes or 0)
    padded_start_utc = program_start_utc
    padded_duration = duration_minutes
    if pre_padding:
        padded_start_utc = program_start_utc - timedelta(minutes=pre_padding)
        padded_duration += pre_padding
    if post_padding:
        padded_duration += post_padding

    # Build timeshift URL using UTC time
    client = XtreamClient(account.server_url, account.username, account.password)
    source_url = client.build_timeshift_url(data.channel_id, padded_start_utc, padded_duration)

    # Create download record
    download = Download(
        account_id=data.account_id,
        channel_id=data.channel_id,
        channel_name=data.channel_name,
        program_title=data.program.get("title", "Unknown"),
        program_start=program_start,
        program_end=program_end,
        duration_minutes=padded_duration,
        source_url=source_url,
        output_path=os.path.join(download_folder, filename),
        status=DownloadStatus.PENDING.value,
    )

    # Queue the download
    download = await download_manager.queue_download(download)

    return download.to_dict()


@router.get("/{download_id}")
async def get_download(
    download_id: int,
    session: AsyncSession = Depends(get_session)
):
    """Get a specific download."""
    result = await session.execute(
        select(Download).where(Download.id == download_id)
    )
    download = result.scalar_one_or_none()

    if not download:
        raise HTTPException(status_code=404, detail="Download not found")

    return download.to_dict()


@router.delete("/{download_id}")
async def cancel_download(
    download_id: int,
    session: AsyncSession = Depends(get_session)
):
    """Cancel or remove a download."""
    result = await session.execute(
        select(Download).where(Download.id == download_id)
    )
    download = result.scalar_one_or_none()

    if not download:
        raise HTTPException(status_code=404, detail="Download not found")

    if download.status in [
        DownloadStatus.PENDING.value,
        DownloadStatus.DOWNLOADING.value,
        DownloadStatus.PROCESSING.value
    ]:
        # Cancel active/pending download
        await download_manager.cancel_download(download_id)
        return {"status": "cancelled"}
    else:
        # Delete from history
        await session.delete(download)
        await session.commit()
        return {"status": "deleted"}


@router.post("/{download_id}/retry")
async def retry_download(
    download_id: int,
    session: AsyncSession = Depends(get_session)
):
    """Retry a failed download."""
    result = await session.execute(
        select(Download).where(Download.id == download_id)
    )
    download = result.scalar_one_or_none()

    if not download:
        raise HTTPException(status_code=404, detail="Download not found")

    if download.status not in [DownloadStatus.FAILED.value, DownloadStatus.CANCELLED.value]:
        raise HTTPException(status_code=400, detail="Can only retry failed or cancelled downloads")

    success = await download_manager.retry_download(download_id)

    if not success:
        raise HTTPException(status_code=500, detail="Failed to retry download")

    # Refresh download status
    await session.refresh(download)
    return download.to_dict()


@router.websocket("/ws")
async def download_progress_websocket(websocket: WebSocket):
    """WebSocket for real-time download progress updates."""
    await websocket.accept()
    download_manager.register_websocket(websocket)

    try:
        while True:
            # Keep connection alive, handle any client messages
            data = await websocket.receive_text()
            # Could handle client commands here if needed
    except WebSocketDisconnect:
        pass
    finally:
        download_manager.unregister_websocket(websocket)
