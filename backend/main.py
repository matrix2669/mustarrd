import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os

from config import settings
from database import init_db
from api import accounts, channels, downloads, settings as settings_api, schedules, vod


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db()

    # Initialize background tasks
    from services.download_manager import download_manager
    from services.scheduled_manager import scheduled_manager
    download_task = asyncio.create_task(download_manager.process_queue())
    schedule_task = asyncio.create_task(scheduled_manager.process_queue())

    yield

    # Shutdown
    download_task.cancel()
    schedule_task.cancel()
    await asyncio.gather(download_task, schedule_task, return_exceptions=True)


app = FastAPI(
    title=settings.app_name,
    description="Catchup DVR - Xtream Codes Timeshift Downloader",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS for frontend development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routes
app.include_router(accounts.router, prefix="/api/accounts", tags=["accounts"])
app.include_router(channels.router, prefix="/api", tags=["channels"])
app.include_router(downloads.router, prefix="/api/downloads", tags=["downloads"])
app.include_router(schedules.router, prefix="/api/schedules", tags=["schedules"])
app.include_router(vod.router, prefix="/api/vod", tags=["vod"])
app.include_router(settings_api.router, prefix="/api/settings", tags=["settings"])


@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "app": settings.app_name}


# Serve frontend static files in production
if os.path.exists("../frontend/dist"):
    app.mount("/", StaticFiles(directory="../frontend/dist", html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
