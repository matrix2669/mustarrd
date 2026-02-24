from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_or_create_app_settings, require_admin
from database import get_session
from models import XtreamAccount
from services.post_processor import post_processor


router = APIRouter()


class ProcessingProfilePayload(BaseModel):
    profile: Literal[
        "leave_as_is",
        "remux_comskip",
        "transcode_mp4_comskip",
        "transcode_mp4_no_comskip",
    ]


class ComskipPolicyPayload(BaseModel):
    enabled: bool
    acknowledge_unavailable: bool = False


def _processing_profiles(comskip_available: bool):
    return [
        {
            "id": "leave_as_is",
            "label": "Leave Original Stream",
            "description": "Keep original format and skip post-processing.",
            "comskip": False,
            "recommended": False,
            "available": True,
        },
        {
            "id": "remux_comskip",
            "label": "Remux + Comskip",
            "description": "Remove commercials and remux quickly to MKV.",
            "comskip": True,
            "recommended": True,
            "available": comskip_available,
        },
        {
            "id": "transcode_mp4_comskip",
            "label": "Transcode MP4 + Comskip",
            "description": "Remove commercials and re-encode to MP4 for compatibility.",
            "comskip": True,
            "recommended": False,
            "available": comskip_available,
        },
        {
            "id": "transcode_mp4_no_comskip",
            "label": "Transcode MP4 (No Comskip)",
            "description": "Re-encode to MP4 without commercial detection.",
            "comskip": False,
            "recommended": False,
            "available": True,
        },
    ]


def _recommended_profile(comskip_available: bool) -> str:
    if comskip_available:
        return "remux_comskip"
    return "transcode_mp4_no_comskip"


async def _build_status_payload(session: AsyncSession):
    app_settings = await get_or_create_app_settings(session)

    count_result = await session.execute(select(func.count()).select_from(XtreamAccount))
    account_count = int(count_result.scalar() or 0)

    active_count_result = await session.execute(
        select(func.count()).select_from(XtreamAccount).where(XtreamAccount.is_active.is_(True))
    )
    active_account_count = int(active_count_result.scalar() or 0)

    tool_status = post_processor.get_tool_runtime_status()
    comskip_status = tool_status["comskip"]
    comskip_available = bool(comskip_status["available"])

    password_set = bool(app_settings.admin_password_hash)
    security_step = password_set
    account_step = account_count > 0
    processing_step = bool(app_settings.onboarding_processing_confirmed)
    comskip_step = bool(app_settings.onboarding_comskip_confirmed)

    required_steps = [
        {
            "id": "security",
            "title": "Set Admin Password",
            "description": "Protect admin APIs and settings access.",
            "completed": security_step,
            "required": True,
            "cta_route": "/login",
        },
        {
            "id": "account",
            "title": "Add Xtream Account",
            "description": "Connect at least one provider account.",
            "completed": account_step,
            "required": True,
            "cta_route": "/settings?section=accounts",
        },
        {
            "id": "processing",
            "title": "Choose Processing Profile",
            "description": "Pick a default transcode/remux strategy.",
            "completed": processing_step,
            "required": True,
            "cta_route": "/onboarding",
        },
        {
            "id": "comskip",
            "title": "Confirm Comskip Policy",
            "description": "Explicitly confirm commercial-removal behavior.",
            "completed": comskip_step,
            "required": True,
            "cta_route": "/onboarding",
        },
    ]

    completed = all(step["completed"] for step in required_steps if step["required"])

    return {
        "dismissed": bool(app_settings.onboarding_dismissed),
        "completed": completed,
        "show_onboarding": not app_settings.onboarding_dismissed and not completed,
        "password_set": password_set,
        "account_count": account_count,
        "active_account_count": active_account_count,
        "processing_confirmed": processing_step,
        "comskip_confirmed": comskip_step,
        "selected_profile": app_settings.onboarding_selected_profile,
        "comskip_enabled": bool(app_settings.comskip_enabled),
        "recommended_profile": _recommended_profile(comskip_available),
        "profiles": _processing_profiles(comskip_available),
        "steps": required_steps,
        "tools": {
            "comskip": {
                "available": comskip_available,
                "path": comskip_status["path"],
                "error": comskip_status["error"],
            }
        },
    }


@router.get("/status")
async def onboarding_status(
    _admin: None = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    return await _build_status_payload(session)


@router.post("/processing-profile")
async def apply_processing_profile(
    payload: ProcessingProfilePayload,
    _admin: None = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    app_settings = await get_or_create_app_settings(session)
    comskip_available = bool(post_processor.get_tool_runtime_status()["comskip"]["available"])

    if payload.profile == "leave_as_is":
        app_settings.transcode_enabled = False
        app_settings.comskip_enabled = False
    elif payload.profile == "remux_comskip":
        if not comskip_available:
            raise HTTPException(status_code=400, detail="Comskip is not available")
        app_settings.transcode_enabled = True
        app_settings.remux_only = True
        app_settings.transcode_format = "mkv"
        app_settings.comskip_enabled = True
    elif payload.profile == "transcode_mp4_comskip":
        if not comskip_available:
            raise HTTPException(status_code=400, detail="Comskip is not available")
        app_settings.transcode_enabled = True
        app_settings.remux_only = False
        app_settings.transcode_format = "mp4"
        app_settings.comskip_enabled = True
    elif payload.profile == "transcode_mp4_no_comskip":
        app_settings.transcode_enabled = True
        app_settings.remux_only = False
        app_settings.transcode_format = "mp4"
        app_settings.comskip_enabled = False

    app_settings.onboarding_selected_profile = payload.profile
    app_settings.onboarding_processing_confirmed = True
    app_settings.onboarding_dismissed = False
    if app_settings.comskip_enabled:
        app_settings.onboarding_comskip_confirmed = True
    elif comskip_available:
        app_settings.onboarding_comskip_confirmed = True

    await session.commit()
    return await _build_status_payload(session)


@router.post("/comskip-policy")
async def set_comskip_policy(
    payload: ComskipPolicyPayload,
    _admin: None = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    app_settings = await get_or_create_app_settings(session)
    comskip_available = bool(post_processor.get_tool_runtime_status()["comskip"]["available"])

    if payload.enabled and not comskip_available:
        raise HTTPException(status_code=400, detail="Comskip is not available")

    if not comskip_available and not payload.acknowledge_unavailable:
        raise HTTPException(status_code=400, detail="Confirm Comskip fallback before continuing")

    app_settings.comskip_enabled = payload.enabled and comskip_available
    if app_settings.comskip_enabled:
        app_settings.transcode_enabled = True

    app_settings.onboarding_comskip_confirmed = True
    app_settings.onboarding_dismissed = False

    await session.commit()
    return await _build_status_payload(session)


@router.post("/dismiss")
async def dismiss_onboarding(
    _admin: None = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    app_settings = await get_or_create_app_settings(session)
    app_settings.onboarding_dismissed = True
    await session.commit()
    return await _build_status_payload(session)
