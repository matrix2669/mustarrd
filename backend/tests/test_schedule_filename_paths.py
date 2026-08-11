import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from api.schedules import _sanitize_filename


class ScheduleFilenamePathTests(unittest.TestCase):
    def test_nested_custom_filename_preserved(self):
        result = _sanitize_filename(
            "TV Shows/Breaking Bad/Season 02/"
            "Breaking Bad - S02E05 - Breakage.ts"
        )
        self.assertEqual(
            result,
            "TV Shows/Breaking Bad/Season 02/"
            "Breaking Bad - S02E05 - Breakage.ts",
        )

    def test_nested_custom_filename_gets_extension(self):
        result = _sanitize_filename(
            "TV Shows/Breaking Bad/Season 02/"
            "Breaking Bad - S02E05 - Breakage"
        )
        self.assertEqual(
            result,
            "TV Shows/Breaking Bad/Season 02/"
            "Breaking Bad - S02E05 - Breakage.ts",
        )

    def test_parent_segments_cannot_escape(self):
        self.assertEqual(
            _sanitize_filename("../../Escape.ts"),
            "unknown-program/unknown-program/Escape.ts",
        )

    def test_leading_slash_stays_relative(self):
        self.assertEqual(
            _sanitize_filename("/TV Shows/Episode.ts"),
            "TV Shows/Episode.ts",
        )


if __name__ == "__main__":
    unittest.main()
