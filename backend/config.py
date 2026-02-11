from pydantic_settings import BaseSettings
from pathlib import Path
import os
import shutil


def _default_data_root() -> Path:
    configured_root = os.environ.get("CATCHUP_DATA_ROOT")
    if configured_root:
        return Path(configured_root).expanduser().resolve()
    repo_root = Path(__file__).resolve().parents[1]
    return repo_root / "data"

def _using_docker_paths() -> bool:
    if os.environ.get("CATCHUP_DOCKER") == "1":
        return True
    return Path("/.dockerenv").exists()

def is_docker_env() -> bool:
    return _using_docker_paths()


def _default_database_url() -> str:
    if _using_docker_paths():
        return "sqlite+aiosqlite:////app/config/catchup_dvr.db"
    return f"sqlite+aiosqlite:///{_default_data_root() / 'catchup_dvr.db'}"


def _default_download_folder() -> str:
    if _using_docker_paths():
        return "/app/downloads"
    return str(_default_data_root() / "downloads")


def _default_completed_folder() -> str:
    if _using_docker_paths():
        return "/app/completed"
    return str(_default_data_root() / "completed")



class Settings(BaseSettings):
    app_name: str = "Catchup DVR"
    debug: bool = False
    timezone: str = "UTC"

    # Database
    database_url: str = _default_database_url()

    # Downloads
    default_download_folder: str = _default_download_folder()
    default_completed_folder: str = _default_completed_folder()
    max_concurrent_downloads: int = 2

    # EPG Cache
    epg_cache_ttl: int = 3600  # 1 hour in seconds
    epg_refresh_interval_hours: int = 8

    class Config:
        env_file = ".env"
        env_prefix = "CATCHUP_"


settings = Settings()

def _get_config_dir() -> Path:
    db_url = settings.database_url
    prefix = "sqlite+aiosqlite:///"
    if db_url.startswith(prefix):
        db_path = Path(db_url[len(prefix):])
        return db_path.parent
    return Path("./config")


def ensure_config_files() -> Path:
    config_dir = _get_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)

    repo_root = Path(__file__).resolve().parents[1]
    bundled_ini = repo_root / "comskip.ini"
    target_ini = config_dir / "comskip.ini"

    if bundled_ini.exists() and not target_ini.exists():
        shutil.copyfile(bundled_ini, target_ini)

    return config_dir


# Ensure config + data directories exist
Path(settings.default_download_folder).mkdir(parents=True, exist_ok=True)
Path(settings.default_completed_folder).mkdir(parents=True, exist_ok=True)
ensure_config_files()
