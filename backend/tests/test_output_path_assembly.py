"""
Regression test: assembled output-path behaviour, caller -> final path.

The existing test_file_namer*/test_vod_namer* suites exercise the naming
helpers in isolation (filename fragments, collision suffixes, year handling).
What they do NOT cover is how the *callers* (download_builder for catchup,
vod_service for VOD) assemble those fragments together with the settings-driven
download folder into the final ``Download.output_path``.

That assembly was duplicated across both builders and is now centralised in
``services.output_path.OutputPath``.  These tests lock the end-to-end result:
the download folder from AppSettings is honoured AND the right naming rules are
applied, for catchup, movies, and series episodes alike.
"""
import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from models import AppSettings, XtreamAccount
from services.download_builder import build_download_from_program
from services.vod_service import build_movie_download, build_episode_download


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


def _session(account, settings):
    """Mock AsyncSession that returns account then settings (the builders' query order)."""
    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[_ScalarResult(account), _ScalarResult(settings)]
    )
    return session


def _account():
    return XtreamAccount(
        id=1,
        name="Acct",
        server_url="https://provider.example.com",
        username="user",
    )


class CatchupAssemblyTests(unittest.TestCase):
    def test_catchup_path_joins_settings_folder_with_generated_filename(self):
        account = _account()
        settings = AppSettings(download_folder="/recordings")
        program = {
            "title": "Inception",
            "description": "A 2010 sci-fi film",
            "start_time": "2026-03-30T10:00:00",
            "end_time": "2026-03-30T11:00:00",
            "category": "Movies",
        }

        async def run():
            with patch(
                "services.download_builder.resolve_account_password_with_migration",
                new=AsyncMock(return_value="pass"),
            ):
                return await build_download_from_program(
                    _session(account, settings),
                    account_id=1,
                    channel_id="999",
                    channel_name="Cinema",
                    program=program,
                )

        download = asyncio.run(run())
        # Folder from AppSettings + filename produced by the catchup namer (.ts).
        self.assertTrue(
            download.output_path.startswith("/recordings/"),
            download.output_path,
        )
        self.assertTrue(download.output_path.endswith(".ts"), download.output_path)

    def test_catchup_template_subdirectories_are_joined_under_download_folder(self):
        account = _account()
        settings = AppSettings(
            download_folder="/recordings",
            tv_template=(
                "TV Shows/{show}/Season {season:02d}/"
                "{show} - S{season:02d}E{episode:02d} - {title}"
            ),
        )
        program = {
            "title": "Breaking Bad S02E05 - Breakage",
            "description": "",
            "start_time": "2026-03-30T10:00:00",
            "end_time": "2026-03-30T11:00:00",
            "category": "TV Shows",
        }

        async def run():
            with (
                patch(
                    "services.download_builder.resolve_account_password_with_migration",
                    new=AsyncMock(return_value="pass"),
                ),
                patch(
                    "services.download_builder.epg_service.detect_program_type",
                    return_value="tv_show",
                ),
            ):
                return await build_download_from_program(
                    _session(account, settings),
                    account_id=1,
                    channel_id="999",
                    channel_name="AMC",
                    program=program,
                )

        download = asyncio.run(run())
        self.assertEqual(
            download.output_path,
            "/recordings/TV Shows/Breaking Bad/Season 02/"
            "Breaking Bad - S02E05 - Breakage.ts",
        )

    def test_catchup_custom_filename_preserves_safe_subdirectories(self):
        account = _account()
        settings = AppSettings(download_folder="/recordings")
        program = {
            "title": "Whatever",
            "start_time": "2026-03-30T10:00:00",
            "end_time": "2026-03-30T11:00:00",
        }

        async def run():
            with patch(
                "services.download_builder.resolve_account_password_with_migration",
                new=AsyncMock(return_value="pass"),
            ):
                return await build_download_from_program(
                    _session(account, settings),
                    account_id=1,
                    channel_id="999",
                    channel_name="Cinema",
                    program=program,
                    custom_filename=(
                        "TV Shows/Breaking Bad/Season 02/"
                        "Breaking Bad - S02E05 - Breakage.ts"
                    ),
                )

        download = asyncio.run(run())
        self.assertEqual(
            download.output_path,
            "/recordings/TV Shows/Breaking Bad/Season 02/"
            "Breaking Bad - S02E05 - Breakage.ts",
        )

    def test_catchup_custom_filename_cannot_escape_download_folder(self):
        account = _account()
        settings = AppSettings(download_folder="/recordings")
        program = {
            "title": "Whatever",
            "start_time": "2026-03-30T10:00:00",
            "end_time": "2026-03-30T11:00:00",
        }

        async def run():
            with patch(
                "services.download_builder.resolve_account_password_with_migration",
                new=AsyncMock(return_value="pass"),
            ):
                return await build_download_from_program(
                    _session(account, settings),
                    account_id=1,
                    channel_id="999",
                    channel_name="Cinema",
                    program=program,
                    custom_filename="../../Escape.ts",
                )

        download = asyncio.run(run())
        self.assertEqual(
            download.output_path,
            "/recordings/Escape.ts",
        )

    def test_catchup_custom_filename_leading_slash_remains_relative(self):
        account = _account()
        settings = AppSettings(download_folder="/recordings")
        program = {
            "title": "Whatever",
            "start_time": "2026-03-30T10:00:00",
            "end_time": "2026-03-30T11:00:00",
        }

        async def run():
            with patch(
                "services.download_builder.resolve_account_password_with_migration",
                new=AsyncMock(return_value="pass"),
            ):
                return await build_download_from_program(
                    _session(account, settings),
                    account_id=1,
                    channel_id="999",
                    channel_name="Cinema",
                    program=program,
                    custom_filename="/TV Shows/Whatever.ts",
                )

        download = asyncio.run(run())
        self.assertEqual(download.output_path, "/recordings/TV Shows/Whatever.ts")


class MovieAssemblyTests(unittest.TestCase):
    def test_movie_path_uses_settings_folder_and_year_from_release_date(self):
        account = _account()
        settings = AppSettings(download_folder="/movies")

        async def run():
            with patch(
                "services.vod_service.resolve_account_password_with_migration",
                new=AsyncMock(return_value="pass"),
            ):
                return await build_movie_download(
                    _session(account, settings),
                    account_id=1,
                    vod_id="42",
                    title="The Matrix",
                    container_extension="mkv",
                    release_date="1999-03-31",
                )

        download = asyncio.run(run())
        self.assertEqual(download.output_path, "/movies/The Matrix (1999).mkv")

    def test_movie_path_falls_back_to_default_folder_when_settings_blank(self):
        account = _account()
        # No download_folder set -> OutputPath falls back to the configured default.
        settings = AppSettings(download_folder=None)

        async def run():
            with patch(
                "services.vod_service.resolve_account_password_with_migration",
                new=AsyncMock(return_value="pass"),
            ):
                return await build_movie_download(
                    _session(account, settings),
                    account_id=1,
                    vod_id="42",
                    title="Heat",
                    container_extension="mp4",
                    release_date="1995",
                )

        download = asyncio.run(run())
        from config import settings as app_settings
        self.assertEqual(
            download.output_path,
            f"{app_settings.default_download_folder}/Heat (1995).mp4",
        )


class SeriesAssemblyTests(unittest.TestCase):
    def test_series_path_builds_show_and_season_subfolders(self):
        account = _account()
        settings = AppSettings(download_folder="/shows")

        async def run():
            with patch(
                "services.vod_service.resolve_account_password_with_migration",
                new=AsyncMock(return_value="pass"),
            ):
                return await build_episode_download(
                    _session(account, settings),
                    account_id=1,
                    series_id="7",
                    show_name="The Wire",
                    episode_id="e1",
                    season=2,
                    episode_num=5,
                    episode_title="Stray Rounds",
                    container_extension="mkv",
                )

        download = asyncio.run(run())
        self.assertEqual(
            download.output_path,
            "/shows/The Wire/Season 02/S02E05 - The Wire - Stray Rounds.mkv",
        )


if __name__ == "__main__":
    unittest.main()
