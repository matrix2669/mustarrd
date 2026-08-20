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
        self.channel = {"name": "FOX Sports 1"}

    def generate(self, program, template=None):
        settings = {"tv_template": template} if template else {}
        return self.namer.generate_filename(
            program,
            self.channel,
            "tv_show",
            settings,
        )

    def test_structured_episode_uses_custom_tv_template_without_subtitle(self):
        self.assertEqual(
            self.generate(
                {
                    "title": "First Things First",
                    "season_number": 5,
                    "episode_number": 17,
                    "start_time": "2026-08-17T12:00:00+00:00",
                },
                "{show} - S{season:02d}E{episode:02d} - {title}",
            ),
            "First Things First - S05E17.ts",
        )

    def test_raw_unknown_xmltv_season_overrides_onscreen_s00(self):
        self.assertEqual(
            self.generate(
                {
                    "title": "First Things First",
                    "season_number": 0,
                    "episode_number": 158,
                    "episode_onscreen": "S00E158",
                    "episode_xmltv_ns": "-1.157.",
                    "start_time": "2026-08-17T12:00:00+00:00",
                },
                "{show} - S{season:02d}E{episode:02d}",
            ),
            "First Things First - S2026E158.ts",
        )

    def test_missing_raw_marker_uses_airing_year_for_daily_series(self):
        self.assertEqual(
            self.generate({
                "title": "First Things First",
                "season_number": 0,
                "episode_number": 159,
                "start_time": "2026-08-17T12:00:00+00:00",
            }),
            "First Things First - S2026E159.ts",
        )

    def test_explicit_special_season_zero_is_preserved(self):
        self.assertEqual(
            self.generate({
                "title": "Holiday Special",
                "season_number": 0,
                "episode_number": 3,
                "episode_onscreen": "S00E03",
                "start_time": "2026-12-20T20:00:00+00:00",
                "subtitle": "Winter Break",
            }),
            "Holiday Special - S00E03 - Winter Break.ts",
        )

    def test_structured_template_preserves_subdirectories(self):
        filename = self.generate(
            {
                "title": "First Things First",
                "season_number": 0,
                "episode_number": 155,
                "start_time": "2026-08-11T19:00:00+00:00",
            },
            (
                "TV Shows/{show}/Season {season:02d}/"
                "{show} - S{season:02d}E{episode:02d} - {title}"
            ),
        )
        self.assertEqual(
            filename,
            "TV Shows/First Things First/Season 2026/"
            "First Things First - S2026E155.ts",
        )


if __name__ == "__main__":
    unittest.main()
