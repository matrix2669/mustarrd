import ipaddress

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from auth import (
    SESSION_ADMIN_KEY,
    get_or_create_app_settings,
    hash_password,
    require_admin,
    verify_password,
)
from database import get_session
from config import settings


router = APIRouter()


class PasswordPayload(BaseModel):
    password: str = Field(min_length=8, max_length=128)


class ChangePasswordPayload(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


def _is_local_or_private_client(host: str | None) -> bool:
    if not host:
        return False
    if host in {"localhost", "127.0.0.1", "::1"}:
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private


@router.get("/status")
async def auth_status(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    app_settings = await get_or_create_app_settings(session)
    password_set = bool(app_settings.admin_password_hash)
    authenticated = bool(request.session.get(SESSION_ADMIN_KEY)) if password_set else False
    return {
        "authenticated": authenticated,
        "password_set": password_set,
    }


@router.post("/setup")
async def setup_auth(
    payload: PasswordPayload,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    app_settings = await get_or_create_app_settings(session)

    if app_settings.admin_password_hash:
        raise HTTPException(status_code=400, detail="Admin password is already configured")
    if not settings.allow_remote_setup:
        client_host = request.client.host if request.client else None
        if not _is_local_or_private_client(client_host):
            raise HTTPException(
                status_code=403,
                detail="Initial setup is restricted to local/private network clients",
            )

    app_settings.admin_password_hash = hash_password(payload.password)
    await session.commit()

    request.session[SESSION_ADMIN_KEY] = True

    return {
        "status": "configured",
        "authenticated": True,
        "password_set": True,
    }


@router.post("/login")
async def login_auth(
    payload: PasswordPayload,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    app_settings = await get_or_create_app_settings(session)

    if not app_settings.admin_password_hash:
        raise HTTPException(status_code=400, detail="Admin password is not configured")

    if not verify_password(payload.password, app_settings.admin_password_hash):
        raise HTTPException(status_code=401, detail="Invalid password")

    request.session[SESSION_ADMIN_KEY] = True

    return {
        "status": "authenticated",
        "authenticated": True,
        "password_set": True,
    }


@router.post("/logout")
async def logout_auth(request: Request):
    request.session.pop(SESSION_ADMIN_KEY, None)
    return {"status": "logged_out"}


@router.post("/change-password")
async def change_password(
    payload: ChangePasswordPayload,
    _admin: None = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    app_settings = await get_or_create_app_settings(session)

    if not app_settings.admin_password_hash:
        raise HTTPException(status_code=400, detail="Admin password is not configured")

    if not verify_password(payload.current_password, app_settings.admin_password_hash):
        raise HTTPException(status_code=401, detail="Current password is incorrect")

    if payload.current_password == payload.new_password:
        raise HTTPException(status_code=400, detail="New password must be different")

    app_settings.admin_password_hash = hash_password(payload.new_password)
    await session.commit()

    return {"status": "password_updated"}
