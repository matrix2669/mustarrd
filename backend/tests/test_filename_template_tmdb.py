import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.file_namer import FileNamer


class FilenameTemplateTmdbTests(unittest.TestCase):
    def setUp(self):
        self.namer = FileNamer()
        self.channel = {"name": "Test"}

    def test_token_supports_series_movie_and_numeric_ids(self):
        for raw in ("series/133532", "movie/133532", "133532"):
            with self.subTest(raw=raw):
                filename = self.namer.generate_filename(
                    {"title": "Example", "tmdb_id": raw},
                    self.channel,
                    "other",
                    {"default_template": "{title} {tmdb}"},
                )
                self.assertEqual(
                    filename,
                    "Example {tmdb-133532} [tmdbid-133532].ts",
                )

    def test_missing_or_invalid_id_collapses_cleanly(self):
        for raw in (None, "series/not-a-number"):
            with self.subTest(raw=raw):
                filename = self.namer.generate_filename(
                    {"title": "Example", "tmdb_id": raw},
                    self.channel,
                    "other",
                    {"default_template": "{title} {tmdb}"},
                )
                self.assertEqual(filename, "Example.ts")

    def test_movie_template_renders_hint(self):
        filename = self.namer.generate_filename(
            {
                "title": "Example Movie",
                "description": "Released in 2024.",
                "tmdb_id": "movie/12345",
            },
            self.channel,
            "movie",
            {"movie_template": "{title} {tmdb}"},
        )
        self.assertEqual(
            filename,
            "Example Movie {tmdb-12345} [tmdbid-12345].ts",
        )

    def test_token_preserves_template_subdirectories(self):
        filename = self.namer.generate_filename(
            {"title": "Example", "tmdb_id": "series/133532"},
            self.channel,
            "other",
            {"default_template": "TV Shows/{title} {tmdb}/{title}"},
        )
        self.assertEqual(
            filename,
            "TV Shows/Example {tmdb-133532} [tmdbid-133532]/Example.ts",
        )


if __name__ == "__main__":
    unittest.main()
