import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.file_namer import FileNamer


class StructuredFilenameTemplateTests(unittest.TestCase):
    def setUp(self):
        self.namer = FileNamer()

    def test_structured_episode_uses_tv_template_without_subtitle(self):
        filename = self.namer.generate_filename(
            {
                "title": "First Things First",
                "season_number": 5,
                "episode_number": 17,
                "start_time": "2026-08-17T12:00:00+00:00",
            },
            {"name": "FS1"},
            "tv_show",
            {"tv_template": "{show} - S{season:02d}E{episode:02d} - {title}"},
        )
        self.assertEqual(filename, "First Things First - S05E17.ts")

    def test_raw_unknown_xmltv_season_uses_airing_year(self):
        filename = self.namer.generate_filename(
            {
                "title": "First Things First",
                "season_number": 0,
                "episode_number": 158,
                "episode_onscreen": "S00E158",
                "episode_xmltv_ns": "-1.157.",
                "start_time": "2026-08-17T12:00:00+00:00",
            },
            {"name": "FS1"},
            "tv_show",
            {"tv_template": "{show} - S{season:02d}E{episode:02d}"},
        )
        self.assertEqual(filename, "First Things First - S2026E158.ts")

    def test_genuine_season_zero_stays_zero_without_raw_negative_xmltv_season(self):
        for raw in (None, "0.2."):
            with self.subTest(raw=raw):
                filename = self.namer.generate_filename(
                    {
                        "title": "Holiday Special",
                        "season_number": 0,
                        "episode_number": 3,
                        "episode_onscreen": "S00E03",
                        "episode_xmltv_ns": raw,
                        "start_time": "2026-08-17T12:00:00+00:00",
                    },
                    {"name": "Test"},
                    "tv_show",
                    {"tv_template": "{show} - S{season:02d}E{episode:02d}"},
                )
                self.assertEqual(filename, "Holiday Special - S00E03.ts")

    def test_tmdb_token_emits_plex_and_jellyfin_hints(self):
        for raw in ("series/133532", "movie/133532", "133532"):
            with self.subTest(raw=raw):
                filename = self.namer.generate_filename(
                    {
                        "title": "Example",
                        "tmdb_id": raw,
                        "start_time": "2026-08-17T12:00:00+00:00",
                    },
                    {"name": "Test"},
                    "other",
                    {"default_template": "{title} {tmdb}"},
                )
                self.assertEqual(filename, "Example {tmdb-133532} [tmdbid-133532].ts")

    def test_tmdb_token_is_empty_for_missing_or_invalid_id(self):
        for raw in (None, "series/not-a-number"):
            with self.subTest(raw=raw):
                filename = self.namer.generate_filename(
                    {
                        "title": "Example",
                        "tmdb_id": raw,
                        "start_time": "2026-08-17T12:00:00+00:00",
                    },
                    {"name": "Test"},
                    "other",
                    {"default_template": "{title} {tmdb}"},
                )
                self.assertEqual(filename, "Example.ts")


if __name__ == "__main__":
    unittest.main()
