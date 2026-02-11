from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional
import os

from database import get_session
from config import (
    ensure_config_files,
    settings as app_settings,
    is_docker_env,
    is_desktop_env,
    legacy_desktop_download_folder,
    legacy_desktop_completed_folder,
)
from models import AppSettings
from services.download_manager import download_manager
from services.epg_service import epg_service
from services.post_processor import post_processor


router = APIRouter()


def _paths_match(path_a: Optional[str], path_b: Optional[str]) -> bool:
    if not path_a or not path_b:
        return False
    norm_a = os.path.realpath(os.path.abspath(os.path.expanduser(path_a)))
    norm_b = os.path.realpath(os.path.abspath(os.path.expanduser(path_b)))
    return norm_a == norm_b


class SettingsUpdate(BaseModel):
    download_folder: Optional[str] = None
    completed_folder: Optional[str] = None
    tv_template: Optional[str] = None
    movie_template: Optional[str] = None
    sports_template: Optional[str] = None
    default_template: Optional[str] = None
    max_concurrent_downloads: Optional[int] = None
    min_free_space_gb: Optional[int] = None
    default_pre_padding_minutes: Optional[int] = None
    default_post_padding_minutes: Optional[int] = None
    # Post-processing
    transcode_enabled: Optional[bool] = None
    transcode_format: Optional[str] = None
    hw_accel: Optional[str] = None
    transcode_quality: Optional[str] = None
    delete_original_after_transcode: Optional[bool] = None
    remux_only: Optional[bool] = None
    comskip_enabled: Optional[bool] = None
    comskip_path: Optional[str] = None
    comskip_ini_path: Optional[str] = None
    remove_commercials: Optional[bool] = None
    epg_offset_minutes: Optional[int] = None
    show_future_programs: Optional[bool] = None
    launch_on_startup: Optional[bool] = None


NON_NULLABLE_FIELDS = {
    "download_folder",
    "completed_folder",
    "tv_template",
    "movie_template",
    "sports_template",
    "default_template",
    "max_concurrent_downloads",
    "min_free_space_gb",
    "default_pre_padding_minutes",
    "default_post_padding_minutes",
    "transcode_enabled",
    "transcode_format",
    "hw_accel",
    "transcode_quality",
    "delete_original_after_transcode",
    "remux_only",
    "comskip_enabled",
    "remove_commercials",
    "epg_offset_minutes",
    "show_future_programs",
    "launch_on_startup",
}



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

    if not settings.download_folder:
        settings.download_folder = app_settings.default_download_folder
        session.add(settings)
        await session.commit()
        await session.refresh(settings)
    if is_docker_env() and not settings.download_folder.startswith("/app/"):
        settings.download_folder = app_settings.default_download_folder
        session.add(settings)
        await session.commit()
        await session.refresh(settings)
    if not is_docker_env() and settings.download_folder.startswith("/app/"):
        settings.download_folder = app_settings.default_download_folder
        session.add(settings)
        await session.commit()
        await session.refresh(settings)
    if not settings.completed_folder:
        settings.completed_folder = app_settings.default_completed_folder
        session.add(settings)
        await session.commit()
        await session.refresh(settings)

    # Desktop builds now default to the OS Downloads directory.
    # Migrate legacy desktop defaults stored under CATCHUP_DATA_ROOT.
    if is_desktop_env():
        legacy_download = legacy_desktop_download_folder()
        legacy_completed = legacy_desktop_completed_folder()

        if _paths_match(settings.download_folder, legacy_download):
            settings.download_folder = app_settings.default_download_folder
            session.add(settings)
            await session.commit()
            await session.refresh(settings)

        if _paths_match(settings.completed_folder, legacy_completed):
            settings.completed_folder = app_settings.default_completed_folder
            session.add(settings)
            await session.commit()
            await session.refresh(settings)
    if is_docker_env() and not settings.completed_folder.startswith("/app/"):
        settings.completed_folder = app_settings.default_completed_folder
        session.add(settings)
        await session.commit()
        await session.refresh(settings)
    if not is_docker_env() and settings.completed_folder.startswith("/app/"):
        settings.completed_folder = app_settings.default_completed_folder
        session.add(settings)
        await session.commit()
        await session.refresh(settings)

    if settings.default_pre_padding_minutes is None:
        settings.default_pre_padding_minutes = 1
        session.add(settings)
        await session.commit()
        await session.refresh(settings)

    if settings.min_free_space_gb is None:
        settings.min_free_space_gb = 25
        session.add(settings)
        await session.commit()
        await session.refresh(settings)

    if settings.default_post_padding_minutes is None:
        settings.default_post_padding_minutes = 5
        session.add(settings)
        await session.commit()
        await session.refresh(settings)

    if settings.launch_on_startup is None:
        settings.launch_on_startup = True
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
        if value is None and field in NON_NULLABLE_FIELDS:
            continue
        if field == "epg_offset_minutes" and value is not None:
            value = int(value)
        if field in {"default_pre_padding_minutes", "default_post_padding_minutes"} and value is not None:
            value = int(value)
        if field == "min_free_space_gb" and value is not None:
            value = int(value)
        setattr(settings, field, value)

    # If comskip is enabled, ensure transcoding is on.
    if update_dict.get("comskip_enabled") is True:
        settings.transcode_enabled = True
        if settings.remove_commercials:
            settings.remux_only = False

    await session.commit()
    await session.refresh(settings)

    # Update download manager if max concurrent changed
    if update_data.max_concurrent_downloads is not None:
        download_manager.set_max_concurrent(update_data.max_concurrent_downloads)

    if "epg_offset_minutes" in update_dict:
        epg_service.clear_cache()

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
            "path": post_processor.get_ffmpeg_path(),
            "description": "Required for transcoding to MP4/MKV formats",
            "install_hint": "Included in the Docker image; install ffmpeg if running locally.",
        },
        "comskip": {
            "available": post_processor.comskip_available,
            "path": post_processor.get_comskip_path(),
            "description": "Commercial detection and removal",
            "install_hint": "Included in the Docker image; build comskip if running locally.",
        },
        "transcode_formats": ["ts", "mp4", "mkv"],
        "hardware_accels": post_processor.get_available_hardware_accels(),
        "quality_presets": [
            {"id": "fast", "name": "Fast", "description": "Faster encoding, larger file size"},
            {"id": "balanced", "name": "Balanced", "description": "Good balance of speed and quality"},
            {"id": "quality", "name": "Quality", "description": "Best quality, slower encoding"},
        ],
    }
