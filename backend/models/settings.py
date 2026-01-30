from sqlalchemy import String, Integer, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from database import Base


class AppSettings(Base):
    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    download_folder: Mapped[str] = mapped_column(String(1000), default="./data/downloads")

    # Naming templates
    tv_template: Mapped[str] = mapped_column(
        String(500),
        default="{show} - S{season:02d}E{episode:02d} - {title}"
    )
    movie_template: Mapped[str] = mapped_column(
        String(500),
        default="{title} ({year})"
    )
    sports_template: Mapped[str] = mapped_column(
        String(500),
        default="{title} - {date}"
    )
    default_template: Mapped[str] = mapped_column(
        String(500),
        default="{channel} - {title} - {date}"
    )

    max_concurrent_downloads: Mapped[int] = mapped_column(Integer, default=2)

    # Post-processing options
    transcode_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    transcode_format: Mapped[str] = mapped_column(String(10), default="mp4")  # ts, mp4, mkv
    hw_accel: Mapped[str] = mapped_column(String(20), default="cpu")  # cpu, videotoolbox, nvenc, amf, qsv, vaapi
    transcode_quality: Mapped[str] = mapped_column(String(20), default="balanced")  # fast, balanced, quality
    delete_original_after_transcode: Mapped[bool] = mapped_column(Boolean, default=True)

    comskip_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    comskip_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    comskip_ini_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    remove_commercials: Mapped[bool] = mapped_column(Boolean, default=True)  # vs just marking

    def to_dict(self):
        return {
            "id": self.id,
            "download_folder": self.download_folder,
            "tv_template": self.tv_template,
            "movie_template": self.movie_template,
            "sports_template": self.sports_template,
            "default_template": self.default_template,
            "max_concurrent_downloads": self.max_concurrent_downloads,
            "transcode_enabled": self.transcode_enabled,
            "transcode_format": self.transcode_format,
            "hw_accel": self.hw_accel,
            "transcode_quality": self.transcode_quality,
            "delete_original_after_transcode": self.delete_original_after_transcode,
            "comskip_enabled": self.comskip_enabled,
            "comskip_path": self.comskip_path,
            "comskip_ini_path": self.comskip_ini_path,
            "remove_commercials": self.remove_commercials,
        }
