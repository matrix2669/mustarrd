import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from api.vod import (
    MovieDownloadRequest,
    SeriesDownloadRequest,
    _extract_tmdb_id,
    _resolve_provider_tmdb_id,
)
from services.output_path import output_path
from services.vod_service import _clean_episode_title


MOVIE_TEMPLATE = "Movies/{title} ({year}) {tmdb}/{title} ({year})"
TV_TEMPLATE = (
    "TV Shows/{show} {tmdb}/Season {season:02d}/"
    "{show} - S{season:02d}E{episode:02d} - {title}"
)


class MovieDownloadRequestMetadataTests(unittest.TestCase):
    def test_numeric_release_year_is_accepted(self):
        request = MovieDownloadRequest(
            account_id=1,
            vod_id="42",
            name="Example Movie",
            release_date=2026,
        )
        self.assertEqual(str(request.release_date), "2026")

    def test_numeric_tmdb_id_is_accepted(self):
        request = MovieDownloadRequest(
            account_id=1,
            vod_id="42",
            name="Example Movie",
            tmdb_id=123456,
        )
        self.assertEqual(str(request.tmdb_id), "123456")

    def test_series_numeric_tmdb_id_is_accepted(self):
        request = SeriesDownloadRequest(
            account_id=1,
            series_id="7",
            series_name="The Wire",
            tmdb_id=1438,
            episodes=[],
        )
        self.assertEqual(str(request.tmdb_id), "1438")


class ProviderTmdbMetadataTests(unittest.TestCase):
    def test_extracts_bad_monkey_series_detail_shape(self):
        self.assertEqual(
            _extract_tmdb_id({"info": {"tmdb": "130853"}}),
            "130853",
        )

    def test_prefers_info_tmdb_id(self):
        self.assertEqual(
            _extract_tmdb_id(
                {
                    "info": {"tmdb_id": 1438, "tmdb": "9999"},
                    "tmdb_id": "8888",
                }
            ),
            "1438",
        )

    def test_falls_back_to_top_level_tmdb_id(self):
        self.assertEqual(_extract_tmdb_id({"tmdb_id": 693134}), "693134")

    def test_ignores_empty_provider_values(self):
        self.assertIsNone(_extract_tmdb_id({"info": {"tmdb_id": "", "tmdb": None}}))


class ProviderTmdbFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_uses_an_isolated_lookup_session(self):
        lookup_session = MagicMock()
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=lookup_session)
        context.__aexit__ = AsyncMock(return_value=None)

        account = MagicMock()
        client = MagicMock()
        client.get_vod_info = AsyncMock(return_value={"info": {"tmdb_id": 693134}})
        client.close = AsyncMock()

        with (
            patch("api.vod.async_session_maker", return_value=context),
            patch("api.vod._get_account", new=AsyncMock(return_value=account)) as get_account,
            patch("api.vod._get_client", new=AsyncMock(return_value=client)) as get_client,
        ):
            result = await _resolve_provider_tmdb_id(1, "42", "movie")

        self.assertEqual(result, "693134")
        get_account.assert_awaited_once_with(lookup_session, 1)
        get_client.assert_awaited_once_with(lookup_session, account)
        client.close.assert_awaited_once()


class VodEpisodeTitleMetadataTests(unittest.TestCase):
    def test_strips_provider_show_and_episode_prefix(self):
        self.assertEqual(
            _clean_episode_title(
                "Bad Monkey - S01E01 - The Floating-Human-Body-Parts Capital of America",
                1,
                1,
            ),
            "The Floating-Human-Body-Parts Capital of America",
        )

    def test_keeps_legitimate_title_containing_episode_marker(self):
        self.assertEqual(
            _clean_episode_title("The S01E01 Mystery", 1, 1),
            "The S01E01 Mystery",
        )


class VodMovieTemplateMetadataTests(unittest.TestCase):
    def test_default_vod_movie_path_is_unchanged(self):
        result = output_path.for_movie(
            {"download_folder": "/downloads"},
            "Dune: Part Two (2024)",
            "mkv",
            release_date="2024",
        )
        self.assertEqual(result, "/downloads/Dune - Part Two (2024).mkv")

    def test_movie_template_uses_tmdb_tags_and_subdirectories(self):
        result = output_path.for_movie(
            {
                "download_folder": "/downloads",
                "movie_template": MOVIE_TEMPLATE,
            },
            "Dune: Part Two (2024)",
            "mkv",
            release_date="2024",
            tmdb_id="693134",
        )
        self.assertEqual(
            result,
            "/downloads/Movies/Dune - Part Two (2024) {tmdb-693134} [tmdbid-693134]/"
            "Dune - Part Two (2024).mkv",
        )

    def test_tmdb_url_is_normalized_to_numeric_id(self):
        result = output_path.for_movie(
            {
                "download_folder": "/downloads",
                "movie_template": MOVIE_TEMPLATE,
            },
            "Dune: Part Two",
            "mp4",
            release_date="2024-03-01",
            tmdb_id="https://www.themoviedb.org/movie/693134",
        )
        self.assertIn("{tmdb-693134} [tmdbid-693134]", result)
        self.assertTrue(result.endswith("/Dune - Part Two (2024).mp4"), result)

    def test_missing_tmdb_id_collapses_cleanly(self):
        result = output_path.for_movie(
            {
                "download_folder": "/downloads",
                "movie_template": MOVIE_TEMPLATE,
            },
            "Dune: Part Two",
            "mp4",
            release_date="2024",
            tmdb_id=None,
        )
        self.assertEqual(
            result,
            "/downloads/Movies/Dune - Part Two (2024)/Dune - Part Two (2024).mp4",
        )
        self.assertNotIn("tmdb", result.lower())


class VodSeriesTemplateMetadataTests(unittest.TestCase):
    def test_tv_template_applies_to_vod_episode(self):
        result = output_path.for_series_episode(
            {
                "download_folder": "/downloads",
                "tv_template": TV_TEMPLATE,
            },
            "The Wire",
            2,
            5,
            "Stray Rounds",
            "mkv",
            episode_id="e1",
            tmdb_id="1438",
        )
        self.assertEqual(
            result,
            "/downloads/TV Shows/The Wire {tmdb-1438} [tmdbid-1438]/Season 02/"
            "The Wire - S02E05 - Stray Rounds.mkv",
        )

    def test_tv_template_without_tmdb_collapses_cleanly(self):
        result = output_path.for_series_episode(
            {
                "download_folder": "/downloads",
                "tv_template": TV_TEMPLATE,
            },
            "The Wire",
            2,
            5,
            "Stray Rounds",
            "mkv",
            episode_id="e1",
            tmdb_id=None,
        )
        self.assertEqual(
            result,
            "/downloads/TV Shows/The Wire/Season 02/"
            "The Wire - S02E05 - Stray Rounds.mkv",
        )

    def test_missing_tv_template_keeps_legacy_vod_hierarchy(self):
        result = output_path.for_series_episode(
            {"download_folder": "/downloads"},
            "The Wire",
            2,
            5,
            "Stray Rounds",
            "mkv",
            episode_id="e1",
        )
        self.assertEqual(
            result,
            "/downloads/The Wire/Season 02/S02E05 - The Wire - Stray Rounds.mkv",
        )


if __name__ == "__main__":
    unittest.main()
