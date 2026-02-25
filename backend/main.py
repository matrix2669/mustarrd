import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.middleware.sessions import SessionMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import select
from starlette.responses import JSONResponse
import os

from config import settings
from database import async_session_maker, init_db
from api import (
    accounts,
    auth,
    channels,
    downloads,
    settings as settings_api,
    schedules,
    vod,
    epg,
    logs,
    onboarding,
    admin_users,
    admin_plex,
)
from models import AppSettings
from services.server_log_bridge import start_server_log_bridge, stop_server_log_bridge


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db()
    logging.getLogger("uvicorn.access").disabled = True
    start_server_log_bridge(asyncio.get_running_loop())

    # Initialize background tasks
    from services.download_manager import download_manager
    from services.scheduled_manager import scheduled_manager
    from services.epg_ingest_manager import epg_ingest_manager
    await download_manager.recover_incomplete_downloads()
    download_task = asyncio.create_task(download_manager.process_queue())
    post_process_task = asyncio.create_task(download_manager.process_post_queue())
    schedule_task = asyncio.create_task(scheduled_manager.process_queue())
    epg_task = asyncio.create_task(epg_ingest_manager.process_queue())

    yield

    # Shutdown
    stop_server_log_bridge()
    download_task.cancel()
    post_process_task.cancel()
    schedule_task.cancel()
    epg_task.cancel()
    await asyncio.gather(download_task, post_process_task, schedule_task, epg_task, return_exceptions=True)


app = FastAPI(
    title=settings.app_name,
    description="Catchup DVR - Xtream Codes Timeshift Downloader",
    version="1.0.0",
    lifespan=lifespan,
)

SETUP_ALLOWED_PATHS = {
    "/api/auth/status",
    "/api/auth/setup",
    "/api/health",
}


async def _is_admin_password_configured() -> bool:
    try:
        async with async_session_maker() as session:
            result = await session.execute(select(AppSettings.admin_password_hash).limit(1))
            password_hash = result.scalar_one_or_none()
            return bool(password_hash)
    except Exception:
        return False


class SetupLockdownMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        path = scope.get("path", "")
        scope_type = scope.get("type")
        if path.startswith("/api") and path not in SETUP_ALLOWED_PATHS and not await _is_admin_password_configured():
            if scope_type == "http" and scope.get("method") != "OPTIONS":
                response = JSONResponse(
                    status_code=423,
                    content={"detail": "Initial admin setup is required"},
                )
                await response(scope, receive, send)
                return
            if scope_type == "websocket":
                await send(
                    {
                        "type": "websocket.close",
                        "code": 1008,
                        "reason": "Initial admin setup is required",
                    }
                )
                return

        await self.app(scope, receive, send)


# CORS for frontend development
app.add_middleware(SetupLockdownMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    same_site="lax",
    https_only=settings.session_https_only,
)

# API routes
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(accounts.router, prefix="/api/accounts", tags=["accounts"])
app.include_router(channels.router, prefix="/api", tags=["channels"])
app.include_router(downloads.router, prefix="/api/downloads", tags=["downloads"])
app.include_router(schedules.router, prefix="/api/schedules", tags=["schedules"])
app.include_router(vod.router, prefix="/api/vod", tags=["vod"])
app.include_router(settings_api.router, prefix="/api/settings", tags=["settings"])
app.include_router(epg.router, prefix="/api", tags=["epg"])
app.include_router(logs.router, prefix="/api", tags=["logs"])
app.include_router(onboarding.router, prefix="/api/onboarding", tags=["onboarding"])
app.include_router(admin_users.router, prefix="/api/admin", tags=["admin-users"])
app.include_router(admin_plex.router, prefix="/api/admin", tags=["admin-plex"])


@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "app": settings.app_name}


def _resolve_frontend_dist() -> Path | None:
    configured_path = os.environ.get("CATCHUP_FRONTEND_DIST")
    if configured_path:
        configured_dist = Path(configured_path).expanduser().resolve()
        if (configured_dist / "index.html").exists():
            return configured_dist

    candidate_roots = [
        Path(__file__).resolve().parents[1] / "frontend" / "dist",
        Path(__file__).resolve().parent / "frontend" / "dist",
    ]

    for candidate in candidate_roots:
        if (candidate / "index.html").exists():
            return candidate

    return None


FRONTEND_DIST = _resolve_frontend_dist()


@app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
async def frontend_index():
    if FRONTEND_DIST is None:
        raise HTTPException(status_code=404, detail="Frontend is not built")
    return FileResponse(FRONTEND_DIST / "index.html")


@app.api_route("/{full_path:path}", methods=["GET", "HEAD"], include_in_schema=False)
async def frontend_routes(full_path: str):
    if full_path.startswith("api/") or full_path == "api":
        raise HTTPException(status_code=404, detail="Not found")

    if FRONTEND_DIST is None:
        raise HTTPException(status_code=404, detail="Frontend is not built")

    requested_path = (FRONTEND_DIST / full_path).resolve()

    if requested_path.is_file() and requested_path.is_relative_to(FRONTEND_DIST):
        return FileResponse(requested_path)

    return FileResponse(FRONTEND_DIST / "index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=4177, reload=True, access_log=False)
