import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from api.vod import _external_output_path, _validate_external_source_url


class ExternalVODRequestTests(unittest.TestCase):
    def test_accepts_absolute_http_source(self):
        url = "https://provider.example/movie/user/pass/123.mkv"
        self.assertEqual(_validate_external_source_url(url), url)

    def test_rejects_non_http_source(self):
        with self.assertRaises(ValueError):
            _validate_external_source_url("file:///etc/passwd")

    def test_rejects_source_without_host(self):
        with self.assertRaises(ValueError):
            _validate_external_source_url("https:///movie/123.mkv")

    def test_resolves_relative_output_under_download_root(self):
        result = _external_output_path(
            "/downloads",
            "mustarrd/Movies/Movie (2026)/Movie.2026.2160p.mkv",
        )
        self.assertEqual(
            result,
            "/downloads/mustarrd/Movies/Movie (2026)/Movie.2026.2160p.mkv",
        )

    def test_rejects_parent_traversal(self):
        with self.assertRaises(ValueError):
            _external_output_path("/downloads", "../completed/movie.mkv")

    def test_rejects_windows_style_parent_traversal(self):
        with self.assertRaises(ValueError):
            _external_output_path("/downloads", "mustarrd\\..\\..\\escape.mkv")

    def test_rejects_absolute_output_path(self):
        with self.assertRaises(ValueError):
            _external_output_path("/downloads", "/tmp/movie.mkv")


if __name__ == "__main__":
    unittest.main()
