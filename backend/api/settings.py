from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional
import os
import platform
import tempfile
import zipfile
import hashlib
import urllib.request
import asyncio
import subprocess
from pathlib import Path

from database import get_session
from config import ensure_config_files, settings as app_settings
from models import AppSettings
from services.download_manager import download_manager
from services.epg_service import epg_service
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
    remux_only: Optional[bool] = None
    comskip_enabled: Optional[bool] = None
    comskip_path: Optional[str] = None
    comskip_ini_path: Optional[str] = None
    remove_commercials: Optional[bool] = None
    epg_offset_minutes: Optional[int] = None


NON_NULLABLE_FIELDS = {
    "download_folder",
    "tv_template",
    "movie_template",
    "sports_template",
    "default_template",
    "max_concurrent_downloads",
    "transcode_enabled",
    "transcode_format",
    "hw_accel",
    "transcode_quality",
    "delete_original_after_transcode",
    "remux_only",
    "comskip_enabled",
    "remove_commercials",
    "epg_offset_minutes",
}


MACOS_FFMPEG_BUILDS = {
    "arm64": {
        "ffmpeg": {
            "url": "https://www.osxexperts.net/ffmpeg80arm.zip",
            "sha256": "f5d3a7de3c926c932e3959031823d13ae0edc7f85b083f35fb66e2fdf7d9dcc4",
        },
        "ffprobe": {
            "url": "https://www.osxexperts.net/ffprobe80arm.zip",
            "sha256": "fd4c41f9b6a5a8bdcb7f5155d56565a2e0b7f0f4c4039ccf4b8cff1f0a0dad3b",
        },
        "ffplay": {
            "url": "https://www.osxexperts.net/ffplay80arm.zip",
            "sha256": "e6a70e5b003613b10a4c6872c857b41f8c52c9f638d5a26a2c1f1f195f96c1a1",
        },
    },
    "x86_64": {
        "ffmpeg": {
            "url": "https://www.osxexperts.net/ffmpeg80intel.zip",
            "sha256": "7f96a9c3b9f9d68d54279cadbde60f506075f5c7e0c29d8f5a5b2e15d227f9e7",
        },
        "ffprobe": {
            "url": "https://www.osxexperts.net/ffprobe80intel.zip",
            "sha256": "f86ac56c8a2a7b9d1c99b9f8eab4c78858e77f916cc1d3a6fd0b7bcf030f1e63",
        },
        "ffplay": {
            "url": "https://www.osxexperts.net/ffplay80intel.zip",
            "sha256": "7007f1d1142fbca2dc8f0bd9b45a7b1b8f66f888a5b58d8f1d8b7e5f95a7f5ce",
        },
    },
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

    if not settings.download_folder or settings.download_folder.startswith("./data"):
        settings.download_folder = app_settings.default_download_folder
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


@router.post("/install-ffmpeg-macos")
async def install_ffmpeg_macos():
    if platform.system() != "Darwin":
        raise HTTPException(status_code=400, detail="macOS only")

    machine = platform.machine().lower()
    if machine not in MACOS_FFMPEG_BUILDS:
        raise HTTPException(status_code=400, detail=f"Unsupported macOS arch: {machine}")

    repo_root = Path(__file__).resolve().parents[2]
    target_dir = repo_root / "tools" / "bin" / ("macos-arm64" if machine == "arm64" else "macos-x86_64")
    target_dir.mkdir(parents=True, exist_ok=True)

    def download_and_install():
        for name, info in MACOS_FFMPEG_BUILDS[machine].items():
            with urllib.request.urlopen(info["url"]) as response:
                data = response.read()
            digest = hashlib.sha256(data).hexdigest()
            if digest.lower() != info["sha256"].lower():
                raise Exception(f"SHA256 mismatch for {name}")

            with tempfile.TemporaryDirectory() as tmpdir:
                zip_path = Path(tmpdir) / f"{name}.zip"
                zip_path.write_bytes(data)
                with zipfile.ZipFile(zip_path, "r") as zf:
                    zf.extractall(tmpdir)

                extracted = None
                for candidate in Path(tmpdir).rglob(name):
                    if candidate.is_file():
                        extracted = candidate
                        break
                if not extracted:
                    raise Exception(f"{name} binary not found in zip")

                dest = target_dir / name
                dest.write_bytes(extracted.read_bytes())
                os.chmod(dest, 0o755)

                # Remove quarantine
                subprocess.run(["xattr", "-dr", "com.apple.quarantine", str(dest)], check=False)
                subprocess.run(["xattr", "-cr", str(dest)], check=False)

                # Apple Silicon requires signing
                if machine == "arm64":
                    subprocess.run(["codesign", "-s", "-", str(dest)], check=False)

        return {
            "installed": True,
            "path": str(target_dir),
        }

    try:
        result = await asyncio.to_thread(download_and_install)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    return result


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
    system = platform.system()
    machine = platform.machine().lower()
    macos_supported = system == "Darwin" and machine in MACOS_FFMPEG_BUILDS
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
        "platform": {
            "system": system,
            "machine": machine,
        },
        "macos_ffmpeg": {
            "supported": macos_supported,
            "version": "8.0",
            "source": "osxexperts.net",
        },
        "transcode_formats": ["ts", "mp4", "mkv"],
        "hardware_accels": post_processor.get_available_hardware_accels(),
        "quality_presets": [
            {"id": "fast", "name": "Fast", "description": "Faster encoding, larger file size"},
            {"id": "balanced", "name": "Balanced", "description": "Good balance of speed and quality"},
            {"id": "quality", "name": "Quality", "description": "Best quality, slower encoding"},
        ],
    }
