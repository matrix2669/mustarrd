import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import require_admin, AuthContext, get_or_create_app_settings
from database import get_session
from models import PlexServer
from services.credential_crypto import credential_crypto
from services.plex_service import plex_service


router = APIRouter()
logger = logging.getLogger(__name__)

SUPPORTED_PLEX_OUTBOUND_POLICIES = {"resource_connections_only"}


class PlexIntegrationPayload(BaseModel):
    resource_id: str = Field(min_length=1)
    resource_name: str | None = None
    connection_uri: str | None = None
    base_url: str | None = None
    machine_identifier: str | None = None
    library_section_ids: list[str] = Field(default_factory=list)
    auto_allow_all_server_users: bool = True
    enabled: bool = True
    plex_outbound_policy: str = "resource_connections_only"


class PlexConnectCompletePayload(BaseModel):
    pin_id: int = Field(ge=1)


class PlexLibrariesPayload(BaseModel):
    connection_uri: str | None = None
    base_url: str | None = None


def _get_session_token(request: Request) -> str | None:
    return request.session.get("plex_admin_token")


async def _resolve_admin_plex_token(request: Request, session: AsyncSession) -> str | None:
    token = _get_session_token(request)
    if token:
        return token

    result = await session.execute(select(PlexServer).order_by(PlexServer.id.asc()))
    row = result.scalars().first()
    if not row:
        return None

    encrypted = row.access_token_encrypted or row.token_encrypted
    if not encrypted:
        return None

    try:
        return credential_crypto.decrypt(encrypted)
    except Exception:
        logger.exception("Stored Plex token decryption failed for admin operation")
        return None


def _validate_policy(value: str | None) -> str:
    policy = (value or "resource_connections_only").strip()
    if policy not in SUPPORTED_PLEX_OUTBOUND_POLICIES:
        raise HTTPException(status_code=400, detail="Unsupported Plex outbound policy")
    return policy


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
    session: AsyncSession = Depends(get_session),
):
    token = await _resolve_admin_plex_token(request, session)
    if not token:
        raise HTTPException(status_code=401, detail="Plex account is not connected")

    try:
        resources = await plex_service.list_owned_resources(token)
    except Exception:
        logger.exception("Plex resource listing failed")
        raise HTTPException(status_code=400, detail="Unable to list Plex resources")
    return resources


@router.post("/plex/resources/{resource_id}/libraries")
async def list_resource_libraries(
    resource_id: str,
    request: Request,
    _admin: AuthContext = Depends(require_admin),
    payload: PlexLibrariesPayload | None = None,
    session: AsyncSession = Depends(get_session),
):
    token = await _resolve_admin_plex_token(request, session)
    if not token:
        raise HTTPException(status_code=401, detail="Plex account is not connected")

    try:
        resources = await plex_service.list_owned_resources(token)
    except Exception:
        logger.exception("Plex resource listing failed during libraries lookup")
        raise HTTPException(status_code=400, detail="Unable to verify Plex resources")
    resource = next((r for r in resources if str(r.get("resource_id")) == str(resource_id)), None)
    if not resource:
        raise HTTPException(status_code=404, detail="Plex resource not found")

    requested_uri = (payload.connection_uri if payload else None) or (payload.base_url if payload else None)
    requested_uri = requested_uri or resource.get("base_url")

    allowed_uris = plex_service.allowed_resource_connection_uris(resources, resource_id)
    try:
        if not requested_uri:
            raise HTTPException(status_code=400, detail="No reachable Plex connection found for selected resource")
        connection = plex_service.resolve_resource_connection(resources, resource_id, requested_uri)
        if not connection:
            raise HTTPException(status_code=400, detail="Selected Plex connection is invalid for this resource")
        libraries = await plex_service.list_server_libraries(connection["uri"], token, allowed_uris=allowed_uris)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Plex libraries lookup failed resource_id=%s", resource_id)
        raise HTTPException(status_code=400, detail="Unable to list Plex libraries")

    return {
        "resource_id": resource_id,
        "connection_uri": connection["uri"],
        "libraries": libraries,
    }


@router.get("/plex/integration")
async def get_plex_integration(
    _admin: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    result = await session.execute(select(PlexServer).order_by(PlexServer.id.asc()))
    row = result.scalars().first()
    app_settings = await get_or_create_app_settings(session)
    policy = _validate_policy(getattr(app_settings, "plex_outbound_policy", "resource_connections_only"))

    if not row:
        return {
            "plex_outbound_policy": policy,
        }

    payload = row.to_dict()
    payload["library_section_ids"] = plex_service.parse_section_ids(row.library_section_ids)
    payload["token_configured"] = bool(row.access_token_encrypted or row.token_encrypted)
    payload["connection_uri"] = row.connection_uri or row.base_url
    payload["plex_outbound_policy"] = policy
    return payload


@router.put("/plex/integration")
async def save_plex_integration(
    payload: PlexIntegrationPayload,
    request: Request,
    _admin: AuthContext = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    token = await _resolve_admin_plex_token(request, session)
    if not token:
        raise HTTPException(status_code=401, detail="Plex account is not connected")

    policy = _validate_policy(payload.plex_outbound_policy)
    try:
        resources = await plex_service.list_owned_resources(token)
    except Exception:
        logger.exception("Plex resource listing failed during save")
        raise HTTPException(status_code=400, detail="Unable to verify Plex resources")
    resource = next((r for r in resources if str(r.get("resource_id")) == str(payload.resource_id)), None)
    if not resource:
        raise HTTPException(status_code=400, detail="Selected Plex resource is not available")

    selected_uri = payload.connection_uri or payload.base_url
    if not selected_uri:
        raise HTTPException(status_code=400, detail="Selected Plex connection is missing")

    connection = plex_service.resolve_resource_connection(resources, payload.resource_id, selected_uri)
    if not connection:
        raise HTTPException(status_code=400, detail="Selected Plex connection is invalid for this resource")

    canonical_uri = connection["uri"]
    app_settings = await get_or_create_app_settings(session)
    app_settings.plex_outbound_policy = policy

    result = await session.execute(select(PlexServer).order_by(PlexServer.id.asc()))
    row = result.scalars().first()

    encrypted = credential_crypto.encrypt(token)
    if not row:
        row = PlexServer(
            base_url=canonical_uri,
            connection_uri=canonical_uri,
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
        row.base_url = canonical_uri
        row.connection_uri = canonical_uri
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

    request.session.pop("plex_admin_token", None)
    request.session.pop("plex_admin_profile", None)

    logger.info(
        "SECURITY_EVENT plex_connection_saved resource_id=%s machine_identifier=%s connection_uri=%s",
        row.resource_id,
        row.machine_identifier,
        row.connection_uri,
    )

    data = row.to_dict()
    data["library_section_ids"] = plex_service.parse_section_ids(row.library_section_ids)
    data["token_configured"] = True
    data["connection_uri"] = row.connection_uri or row.base_url
    data["plex_outbound_policy"] = policy
    return data
