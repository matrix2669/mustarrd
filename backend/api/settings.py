from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional

from database import get_session
from config import ensure_config_files
from models import AppSettings
from services.download_manager import download_manager
from services.post_processor import post_processor


router = APIRouter()


class SettingsUpdate(BaseModel):
    download_folder: Optional[str] = None
    tv_template: Optional[str] = None
    movie_template: Optional[str] = None
    sports_template: Optional[str] = None
    default_template: Optional[str] = None
    max_concurrent_downloads: Optional[int] = None
    # Post-processing
    transcode_enabled: Optional[bool] = None
    transcode_format: Optional[str] = None
    hw_accel: Optional[str] = None
    transcode_quality: Optional[str] = None
    delete_original_after_transcode: Optional[bool] = None
    comskip_enabled: Optional[bool] = None
    comskip_path: Optional[str] = None
    comskip_ini_path: Optional[str] = None
    remove_commercials: Optional[bool] = None


@router.get("")
async def get_settings(session: AsyncSession = Depends(get_session)):
    """Get app settings."""
    result = await session.execute(select(AppSettings))
    settings = result.scalar_one_or_none()

    if not settings:
        # Create default settings
        settings = AppSettings()
        session.add(settings)
        await session.commit()
        await session.refresh(settings)

    config_dir = ensure_config_files()
    default_ini = config_dir / "comskip.ini"
    if settings.comskip_ini_path is None and default_ini.exists():
        settings.comskip_ini_path = str(default_ini)
        session.add(settings)
        await session.commit()
        await session.refresh(settings)

    return settings.to_dict()


@router.put("")
async def update_settings(
    update_data: SettingsUpdate,
    session: AsyncSession = Depends(get_session)
):
    """Update app settings."""
    result = await session.execute(select(AppSettings))
    settings = result.scalar_one_or_none()

    if not settings:
        settings = AppSettings()
        session.add(settings)

    # Update fields
    update_dict = update_data.model_dump(exclude_unset=True)
    for field, value in update_dict.items():
        setattr(settings, field, value)

    await session.commit()
    await session.refresh(settings)

    # Update download manager if max concurrent changed
    if update_data.max_concurrent_downloads is not None:
        download_manager.set_max_concurrent(update_data.max_concurrent_downloads)

    return settings.to_dict()


@router.get("/templates")
async def get_template_variables():
    """Get available template variables for filename customization."""
    return {
        "tv_show": {
            "variables": [
                {"name": "show", "description": "The show name"},
                {"name": "season", "description": "Season number (use :02d for zero-padding)"},
                {"name": "episode", "description": "Episode number (use :02d for zero-padding)"},
                {"name": "title", "description": "Episode title"},
                {"name": "date", "description": "Air date (YYYY-MM-DD)"},
            ],
            "example": "{show} - S{season:02d}E{episode:02d} - {title}",
        },
        "movie": {
            "variables": [
                {"name": "title", "description": "Movie title"},
                {"name": "year", "description": "Release year"},
            ],
            "example": "{title} ({year})",
        },
        "sports": {
            "variables": [
                {"name": "title", "description": "Event title (e.g., 'NFL - Dolphins vs Chargers')"},
                {"name": "date", "description": "Event date (YYYY-MM-DD)"},
                {"name": "channel", "description": "Channel name"},
            ],
            "example": "{title} - {date}",
        },
        "default": {
            "variables": [
                {"name": "channel", "description": "Channel name"},
                {"name": "title", "description": "Program title"},
                {"name": "date", "description": "Air date (YYYY-MM-DD)"},
            ],
            "example": "{channel} - {title} - {date}",
        },
    }


@router.get("/tools")
async def get_tools_status():
    """Check availability of post-processing tools."""
    return {
        "ffmpeg": {
            "available": post_processor.ffmpeg_available,
            "description": "Required for transcoding to MP4/MKV formats",
            "install_hint": "brew install ffmpeg (macOS) or apt install ffmpeg (Linux)",
        },
        "comskip": {
            "available": post_processor.comskip_available,
            "description": "Commercial detection and removal",
            "install_hint": "See https://github.com/erikkaashoek/Comskip for installation",
        },
        "transcode_formats": ["ts", "mp4", "mkv"],
        "hardware_accels": post_processor.get_available_hardware_accels(),
        "quality_presets": [
            {"id": "fast", "name": "Fast", "description": "Faster encoding, larger file size"},
            {"id": "balanced", "name": "Balanced", "description": "Good balance of speed and quality"},
            {"id": "quality", "name": "Quality", "description": "Best quality, slower encoding"},
        ],
    }
