from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, func

from database import get_session
from models import XtreamAccount, AppSettings, EPGProgram
from services.epg_service import epg_service
from services.epg_ingest_manager import epg_ingest_manager


router = APIRouter()


@router.get("/epg/search")
async def search_epg(
    account_id: int = Query(..., ge=1),
    q: str = Query(..., min_length=2),
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
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
async def epg_status():
    return epg_ingest_manager.get_status()
