import sys
import unittest
from pathlib import Path

from starlette.requests import HTTPConnection

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from security import ensure_csrf_token, normalize_origin, origin_is_allowed, request_origin


class SecurityHelpersTests(unittest.TestCase):
    def test_ensure_csrf_token_reuses_existing_session_value(self):
        scope = {"type": "http", "headers": [], "session": {}}
        connection = HTTPConnection(scope)

        first = ensure_csrf_token(connection)
        second = ensure_csrf_token(connection)

        self.assertEqual(first, second)
        self.assertEqual(scope["session"]["csrf_token"], first)

    def test_normalize_origin_discards_path_and_normalizes_case(self):
        self.assertEqual(
            normalize_origin("HTTP://LOCALHOST:4177/some/path"),
            "http://localhost:4177",
        )

    def test_request_origin_prefers_forwarded_proto(self):
        scope = {
            "type": "http",
            "scheme": "http",
            "headers": [
                (b"host", b"example.com"),
                (b"x-forwarded-proto", b"https"),
            ],
            "session": {},
        }

        self.assertEqual(request_origin(scope), "https://example.com")

    def test_origin_is_allowed_for_current_request_origin(self):
        scope = {
            "type": "http",
            "scheme": "https",
            "headers": [
                (b"host", b"app.example.com"),
            ],
            "session": {},
        }

        self.assertTrue(origin_is_allowed("https://app.example.com", scope, []))
        self.assertFalse(origin_is_allowed("https://evil.example.com", scope, []))

    def test_origin_is_allowed_for_configured_cross_origin_frontend(self):
        scope = {
            "type": "http",
            "scheme": "http",
            "headers": [
                (b"host", b"localhost:4177"),
            ],
            "session": {},
        }

        self.assertTrue(
            origin_is_allowed("http://localhost:4178", scope, ["http://localhost:4178"])
        )


if __name__ == "__main__":
    unittest.main()
