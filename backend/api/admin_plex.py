import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import require_admin, AuthContext
from database import get_session
from models import PlexServer
from services.credential_crypto import credential_crypto
from services.plex_service import plex_service


router = APIRouter()
logger = logging.getLogger(__name__)


class PlexServerPayload(BaseModel):
    base_url: str = Field(min_length=1)
    token: str = Field(min_length=1)
    machine_identifier: str | None = None
    library_section_ids: list[str] = Field(default_factory=list)
    auto_allow_all_server_users: bool = True
    enabled: bool = True


class PlexIntegrationPayload(BaseModel):
    resource_id: str = Field(min_length=1)
    resource_name: str | None = None
    base_url: str = Field(min_length=1)
    machine_identifier: str | None = None
    library_section_ids: list[str] = Field(default_factory=list)
    auto_allow_all_server_users: bool = True
    enabled: bool = True


class PlexConnectCompletePayload(BaseModel):
    pin_id: int = Field(ge=1)


def _get_session_token(request: Request) -> str | None:
    return request.session.get("plex_admin_token")


@router.post("/plex/connect/start")
async def connect_start(_admin: AuthContext = Depends(require_admin)):
    pin = await plex_service.create_pin()
    pin["poll_interval_seconds"] = 2
    pin["expires_in"] = pin.get("expires_in") or 300
    return pin


@router.post("/plex/connect/complete")
async def connect_complete(
    request: Request,
    payload: PlexConnectCompletePayload,
    _admin: AuthContext = Depends(require_admin),
):
    pin_data = await plex_service.check_pin(payload.pin_id)
    auth_token = pin_data.get("authToken")
    if not auth_token:
        raise HTTPException(status_code=400, detail="Plex authentication is not complete yet")

    profile = await plex_service.get_user_profile(auth_token)
    request.session["plex_admin_token"] = auth_token
    request.session["plex_admin_profile"] = {
        "id": profile.get("id"),
        "username": profile.get("username"),
        "email": profile.get("email"),
        "title": profile.get("title"),
    }

    return {
        "status": "connected",
        "profile": request.session["plex_admin_profile"],
    }


@router.get("/plex/resources")
async def list_resources(
    request: Request,
    _admin: AuthContext = Depends(require_admin),
):
    token = _get_session_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Plex account is not connected")

    resources = await plex_service.list_owned_resources(token)
    return resources


@router.post("/plex/resources/{resource_id}/libraries")
async def list_resource_libraries(
    resource_id: str,
    request: Request,
    _admin: AuthContext = Depends(require_admin),
):
    token = _get_session_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Plex account is not connected")

    resources = await plex_service.list_owned_resources(token)
    resource = next((r for r in resources if str(r.get("resource_id")) == str(resource_id)), None)
    if not resource:
        raise HTTPException(status_code=404, detail="Plex resource not found")

    base_url = resource.get("base_url")
    if not base_url:
        raise HTTPException(status_code=400, detail="Selected resource has no reachable connection URL")

    try:
        libraries = await plex_service.list_server_libraries(base_url, token)
    except Exception as exc:
        logger.exception("Plex libraries lookup failed resource_id=%s base_url=%s", resource_id, base_url)
        raise HTTPException(status_code=400, detail=str(exc))

    return {
        "resource_id": resource_id,
        "base_url": base_url,
        "libraries": libraries,
    }


@router.get("/plex/integration")
async def get_plex_integration(
    _admin: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(PlexServer).order_by(PlexServer.id.asc()))
    row = result.scalars().first()
    if not row:
        return None
    payload = row.to_dict()
    payload["library_section_ids"] = plex_service.parse_section_ids(row.library_section_ids)
    payload["token_configured"] = bool(row.access_token_encrypted or row.token_encrypted)
    return payload


@router.put("/plex/integration")
async def save_plex_integration(
    payload: PlexIntegrationPayload,
    request: Request,
    _admin: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    token = _get_session_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Plex account is not connected")

    result = await session.execute(select(PlexServer).order_by(PlexServer.id.asc()))
    row = result.scalars().first()

    encrypted = credential_crypto.encrypt(token)
    if not row:
        row = PlexServer(
            base_url=payload.base_url.strip(),
            token_encrypted=encrypted,
            access_token_encrypted=encrypted,
            resource_id=payload.resource_id,
            resource_name=payload.resource_name,
            machine_identifier=payload.machine_identifier,
            library_section_ids=json.dumps(payload.library_section_ids),
            auto_allow_all_server_users=payload.auto_allow_all_server_users,
            enabled=payload.enabled,
        )
        session.add(row)
    else:
        row.base_url = payload.base_url.strip()
        row.token_encrypted = encrypted
        row.access_token_encrypted = encrypted
        row.resource_id = payload.resource_id
        row.resource_name = payload.resource_name
        row.machine_identifier = payload.machine_identifier
        row.library_section_ids = json.dumps(payload.library_section_ids)
        row.auto_allow_all_server_users = payload.auto_allow_all_server_users
        row.enabled = payload.enabled
        row.updated_at = datetime.utcnow()

    await session.commit()
    await session.refresh(row)

    data = row.to_dict()
    data["library_section_ids"] = plex_service.parse_section_ids(row.library_section_ids)
    data["token_configured"] = True
    return data


# Backward compatibility endpoints
@router.get("/plex/server")
async def get_plex_server_compat(
    _admin: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    return await get_plex_integration(_admin, session)


@router.put("/plex/server")
async def upsert_plex_server_compat(
    payload: PlexServerPayload,
    request: Request,
    _admin: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    request.session["plex_admin_token"] = payload.token.strip()
    integration = PlexIntegrationPayload(
        resource_id=payload.machine_identifier or "manual",
        resource_name="Manual",
        base_url=payload.base_url,
        machine_identifier=payload.machine_identifier,
        library_section_ids=payload.library_section_ids,
        auto_allow_all_server_users=payload.auto_allow_all_server_users,
        enabled=payload.enabled,
    )
    return await save_plex_integration(integration, request, _admin, session)


@router.post("/plex/server/test")
async def test_plex_server(
    payload: PlexServerPayload,
    _admin: AuthContext = Depends(require_admin),
):
    try:
        users = await plex_service.list_server_users(payload.base_url, payload.token)
    except Exception as exc:
        logger.exception(
            "Plex server test failed base_url=%s auto_allow_all_server_users=%s enabled=%s library_section_ids=%s",
            payload.base_url,
            payload.auto_allow_all_server_users,
            payload.enabled,
            payload.library_section_ids,
        )
        raise HTTPException(status_code=400, detail=str(exc))

    return {
        "status": "ok",
        "user_count": len(users),
    }


@router.get("/plex/server/users")
async def list_plex_server_users(
    _admin: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(PlexServer).order_by(PlexServer.id.asc()))
    row = result.scalars().first()
    if not row or not row.enabled:
        raise HTTPException(status_code=404, detail="Plex server is not configured")

    try:
        encrypted = row.access_token_encrypted or row.token_encrypted
        token = credential_crypto.decrypt(encrypted)
        users = await plex_service.list_server_users(row.base_url, token)
    except Exception as exc:
        logger.exception(
            "Plex server users listing failed base_url=%s server_id=%s enabled=%s",
            row.base_url,
            row.id,
            row.enabled,
        )
        raise HTTPException(status_code=400, detail=str(exc))

    return users
