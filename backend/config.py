from pydantic_settings import BaseSettings
from pathlib import Path


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

# Ensure data directories exist
Path("./data").mkdir(exist_ok=True)
Path(settings.default_download_folder).mkdir(parents=True, exist_ok=True)
