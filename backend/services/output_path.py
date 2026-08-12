"""Single place that turns a recording target + settings into a completed-file path.

Before this module, ``download_builder`` (catchup) and ``vod_service`` (VOD)
each independently re-queried/read ``AppSettings``, re-resolved the download
folder, and re-assembled the final ``output_path``.  The naming rules for
catchup, movies, and series episodes are genuinely different (template-driven
program naming vs. ``Movie (Year)`` vs. ``Show/Season NN/SnnExx`` subfolders),
so those stay as distinct internals delegated to ``file_namer`` and
``vod_namer``.  What the two callers *shared* — "resolve the download folder
from settings, then join it with a filename" — now lives here, once.

Callers pass the loaded ``AppSettings`` row (or ``None``); folder resolution
and final-path assembly happen inside, so the interface a caller sees is just
"give me the path for this thing".
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
    """Resolve the download folder from settings, falling back to the configured default.

    Both download_builder and vod_service used to do this independently.
    Works whether ``settings`` is an AppSettings row or a plain dict.
    """
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
    """Builds completed-file paths for every kind of recording target.

    One method per target kind.  Each one resolves the download folder and
    returns a full path; callers no longer touch the folder or the filename
    helpers themselves.
    """

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
            filename = custom_filename
            if not filename.endswith(".ts"):
                filename += ".ts"
            filename = file_namer.sanitize_filename(filename.removesuffix(".ts")) + ".ts"
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
        """Completed-file path for a VOD movie.

        Year is taken from ``release_date`` if present, otherwise extracted from
        the title. VOD movies honor the saved ``movie_template`` and can use
        provider-supplied ``{tmdb}``/``{tmdb_id}`` metadata.
        """
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
    ) -> str:
        """Completed-file path for a VOD series episode (with Show/Season folders)."""
        folder = _download_folder(settings)
        return series_episode_output_path(
            folder,
            show_name,
            season,
            episode,
            episode_title,
            extension,
            episode_id=episode_id,
        )


# Global instance, mirroring the file_namer / vod_namer module-level singletons.
output_path = OutputPath()
