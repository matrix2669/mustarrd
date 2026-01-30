from pydantic_settings import BaseSettings
from pathlib import Path
import shutil



class Settings(BaseSettings):
    app_name: str = "Catchup DVR"
    debug: bool = False

    # Database
    database_url: str = "sqlite+aiosqlite:///./data/catchup_dvr.db"

    # Downloads
    default_download_folder: str = "./data/downloads"
    max_concurrent_downloads: int = 2

    # EPG Cache
    epg_cache_ttl: int = 3600  # 1 hour in seconds

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


# Ensure config + download directories exist
Path(settings.default_download_folder).mkdir(parents=True, exist_ok=True)
ensure_config_files()
