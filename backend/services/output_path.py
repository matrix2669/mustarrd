"""Single place that turns a recording target + settings into a completed-file path.

Before this module, ``download_builder`` (catchup) and ``vod_service`` (VOD)
each independently re-queried/read ``AppSettings``, re-resolved the download
folder, and re-assembled the final ``output_path``.  What callers share —
"resolve the download folder from settings, then render the configured naming
policy" — lives here.
"""
import os
from typing import Optional

from config import settings as app_settings
from services.file_namer import file_namer
from services.vod_namer import movie_output_path, series_episode_output_path


def _settings_dict(settings) -> Optional[dict]:
    """Accept either an AppSettings row, a plain dict, or None."""
    if settings is None:
        return None
    if isinstance(settings, dict):
        return settings
    to_dict = getattr(settings, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    return None


def _download_folder(settings) -> str:
    folder = None
    if settings is not None:
        if isinstance(settings, dict):
            folder = settings.get("download_folder")
        else:
            folder = getattr(settings, "download_folder", None)
    if folder:
        return folder
    return app_settings.default_download_folder


class OutputPath:
    """Builds completed-file paths for every kind of recording target."""

    def for_program(
        self,
        settings,
        program: dict,
        channel: dict,
        program_type: str,
        custom_filename: Optional[str] = None,
    ) -> str:
        """Completed-file path for a catchup/timeshift program."""
        folder = _download_folder(settings)
        if custom_filename:
            filename = file_namer.sanitize_custom_filename(custom_filename)
        else:
            filename = file_namer.generate_filename(
                program, channel, program_type, _settings_dict(settings)
            )
        return os.path.join(folder, filename)

    def for_movie(
        self,
        settings,
        title: str,
        extension: Optional[str],
        release_date: Optional[str] = None,
        tmdb_id=None,
    ) -> str:
        """Completed-file path for a VOD movie using ``movie_template``."""
        folder = _download_folder(settings)
        settings_dict = _settings_dict(settings) or {}
        year = file_namer.extract_year(release_date or "") or file_namer.extract_year(title or "")
        return movie_output_path(
            folder,
            title,
            year,
            extension,
            template=settings_dict.get("movie_template"),
            tmdb_id=tmdb_id,
        )

    def for_series_episode(
        self,
        settings,
        show_name: str,
        season: int,
        episode: int,
        episode_title: Optional[str],
        extension: Optional[str],
        episode_id: Optional[str] = None,
        tmdb_id=None,
    ) -> str:
        """Completed-file path for a VOD episode using ``tv_template``."""
        folder = _download_folder(settings)
        settings_dict = _settings_dict(settings) or {}
        return series_episode_output_path(
            folder,
            show_name,
            season,
            episode,
            episode_title,
            extension,
            episode_id=episode_id,
            template=settings_dict.get("tv_template"),
            tmdb_id=tmdb_id,
        )


output_path = OutputPath()
