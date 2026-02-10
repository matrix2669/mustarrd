from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional

from database import get_session
from models import XtreamAccount
from services.epg_service import epg_service
from services.xtream_client import XtreamClient


router = APIRouter()


@router.get("/accounts/{account_id}/categories")
async def get_categories(
    account_id: int,
    session: AsyncSession = Depends(get_session)
):
    """Get channel categories for an account."""
    result = await session.execute(
        select(XtreamAccount).where(XtreamAccount.id == account_id)
    )
    account = result.scalar_one_or_none()

    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    try:
        categories = await epg_service.get_categories(session, account_id)
        return categories
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/accounts/{account_id}/channels")
async def get_channels(
    account_id: int,
    category_id: Optional[str] = Query(None),
    catchup_only: bool = Query(True, description="Only show channels with catchup/timeshift support"),
    session: AsyncSession = Depends(get_session)
):
    """Get channels for an account, optionally filtered by category."""
    result = await session.execute(
        select(XtreamAccount).where(XtreamAccount.id == account_id)
    )
    account = result.scalar_one_or_none()

    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    try:
        client = XtreamClient(account.server_url, account.username, account.password)
        try:
            channels = await client.get_live_streams(category_id)

            if catchup_only:
                # Filter to only channels with catchup enabled
                channels = [ch for ch in channels if ch.get("tv_archive", 0) == 1]

            # Add archive duration info
            for ch in channels:
                ch["tv_archive_duration"] = ch.get("tv_archive_duration", account.catchup_days)

            return channels
        finally:
            await client.close()

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/accounts/{account_id}/channels/{channel_id}/epg")
async def get_channel_epg(
    account_id: int,
    channel_id: str,
    days_back: int = Query(7, ge=1, le=14),
    session: AsyncSession = Depends(get_session)
):
    """Get EPG data for a specific channel."""
    result = await session.execute(
        select(XtreamAccount).where(XtreamAccount.id == account_id)
    )
    account = result.scalar_one_or_none()

    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    try:
        actual_days = min(days_back, account.catchup_days)
        epg_data = await epg_service.get_epg_for_channel(
            session,
            account_id,
            channel_id,
            days_back=actual_days,
        )
        return epg_data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/accounts/{account_id}/channels/{channel_id}/catchup")
async def get_catchup_programs(
    account_id: int,
    channel_id: str,
    days_back: int = Query(7, ge=1, le=14),
    session: AsyncSession = Depends(get_session)
):
    """Get past programs available for catchup/timeshift."""
    result = await session.execute(
        select(XtreamAccount).where(XtreamAccount.id == account_id)
    )
    account = result.scalar_one_or_none()

    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    try:
        # Use the account's catchup_days setting as the maximum
        actual_days = min(days_back, account.catchup_days)
        programs = await epg_service.get_past_programs(
            session, account_id, channel_id, actual_days
        )
        return programs
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/accounts/{account_id}/channels/{channel_id}")
async def get_channel_info(
    account_id: int,
    channel_id: str,
    session: AsyncSession = Depends(get_session)
):
    """Get info for a specific channel."""
    result = await session.execute(
        select(XtreamAccount).where(XtreamAccount.id == account_id)
    )
    account = result.scalar_one_or_none()

    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    try:
        client = XtreamClient(account.server_url, account.username, account.password)
        try:
            channels = await client.get_live_streams()
            channel = next((ch for ch in channels if str(ch.get("stream_id")) == channel_id), None)

            if not channel:
                raise HTTPException(status_code=404, detail="Channel not found")

            return channel
        finally:
            await client.close()

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
