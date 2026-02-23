import asyncio
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, func

from auth import require_admin
from database import get_session
from models import XtreamAccount, AppSettings, EPGProgram
from services.epg_service import epg_service
from services.epg_ingest_manager import epg_ingest_manager


router = APIRouter()


def _log_task_result(task: asyncio.Task):
    try:
        task.result()
    except Exception as exc:
        print(f"EPG refresh task failed: {exc}")


class EPGRefreshRequest(BaseModel):
    force: bool = False


@router.get("/epg/search")
async def search_epg(
    account_id: int = Query(..., ge=1),
    q: str = Query(..., min_length=2),
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _admin: None = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(
        select(XtreamAccount).where(XtreamAccount.id == account_id)
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    settings_result = await session.execute(select(AppSettings))
    app_settings_row = settings_result.scalar_one_or_none()
    epg_offset_minutes = app_settings_row.epg_offset_minutes if app_settings_row else 0

    query = f"%{q.lower()}%"
    result = await session.execute(
        select(EPGProgram)
        .where(
            EPGProgram.account_id == account_id,
            or_(
                func.lower(EPGProgram.title).like(query),
                func.lower(EPGProgram.description).like(query),
            ),
        )
        .order_by(EPGProgram.start_time.desc())
        .limit(limit)
        .offset(offset)
    )
    programs = result.scalars().all()
    return [epg_service.serialize_program(row, epg_offset_minutes) for row in programs]


@router.get("/epg/status")
async def epg_status(_admin: None = Depends(require_admin)):
    return epg_ingest_manager.get_status()


@router.post("/epg/refresh")
async def trigger_epg_refresh(
    request: EPGRefreshRequest,
    _admin: None = Depends(require_admin),
):
    status = epg_ingest_manager.get_status()
    if status.get("running"):
        raise HTTPException(status_code=409, detail="EPG refresh is already running")

    refresh_task = asyncio.create_task(
        epg_ingest_manager.refresh_all_accounts(force=request.force)
    )
    refresh_task.add_done_callback(_log_task_result)

    return {
        "status": "started",
        "force": request.force,
    }
