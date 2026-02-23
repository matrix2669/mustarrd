import mimetypes
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel, conint
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional

from auth import require_admin, require_admin_websocket
from database import get_session
from models import Download, DownloadStatus, XtreamAccount
from services.download_manager import download_manager
from services.file_namer import file_namer
from services.epg_service import epg_service
from services.download_builder import build_download_from_program


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
async def list_downloads(
    _admin: None = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """List all downloads (queue + history)."""
    result = await session.execute(
        select(Download).order_by(Download.created_at.desc())
    )
    downloads = result.scalars().all()
    return [download_manager.merge_progress_snapshot(d.to_dict()) for d in downloads]


@router.get("/queue")
async def get_download_queue(_admin: None = Depends(require_admin)):
    """Get pending and active downloads."""
    return await download_manager.get_queue()


@router.get("/history")
async def get_download_history(_admin: None = Depends(require_admin)):
    """Get completed, failed, and cancelled downloads."""
    return await download_manager.get_history()


@router.post("/preview-filename")
async def preview_filename(
    data: FilenamePreview,
    _admin: None = Depends(require_admin),
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
    _admin: None = Depends(require_admin),
    session: AsyncSession = Depends(get_session)
):
    """Queue a new download."""
    try:
        download = await build_download_from_program(
            session,
            account_id=data.account_id,
            channel_id=data.channel_id,
            channel_name=data.channel_name,
            program=data.program,
            custom_filename=data.custom_filename,
            pre_padding_minutes=data.pre_padding_minutes or 0,
            post_padding_minutes=data.post_padding_minutes or 0,
        )
    except ValueError as exc:
        message = str(exc)
        if "Account not found" in message:
            raise HTTPException(status_code=404, detail=message)
        raise HTTPException(status_code=400, detail=message)

    # Queue the download
    download = await download_manager.queue_download(download)

    return download.to_dict()


@router.get("/{download_id}")
async def get_download(
    download_id: int,
    _admin: None = Depends(require_admin),
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


@router.get("/{download_id}/file")
async def get_download_file(
    download_id: int,
    action: str = Query(default="download", pattern="^(download|play)$"),
    _admin: None = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    """Serve a completed download file for browser download/play actions."""
    result = await session.execute(
        select(Download).where(Download.id == download_id)
    )
    download = result.scalar_one_or_none()

    if not download:
        raise HTTPException(status_code=404, detail="Download not found")

    if download.status != DownloadStatus.COMPLETED.value:
        raise HTTPException(status_code=409, detail="Download is not completed yet")

    if not download.output_path:
        raise HTTPException(status_code=404, detail="No file path available for this download")

    file_path = Path(download.output_path).expanduser()
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Downloaded file was not found on disk")

    media_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
    disposition = "inline" if action == "play" else "attachment"
    safe_filename = file_path.name.replace('"', "")
    headers = {"Content-Disposition": f'{disposition}; filename="{safe_filename}"'}

    return FileResponse(
        path=str(file_path),
        media_type=media_type,
        headers=headers,
    )


@router.delete("/{download_id}")
async def cancel_download(
    download_id: int,
    _admin: None = Depends(require_admin),
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
    _admin: None = Depends(require_admin),
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
async def download_progress_websocket(
    websocket: WebSocket,
    _admin: None = Depends(require_admin_websocket),
):
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
