import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, call, patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.download_manager import (
    DownloadManager,
    VOD_HTTP_RETRY_MAX_SECONDS,
    VOD_RETRYABLE_HTTP_STATUSES,
    _http_status_from_exception,
)


class VODHTTPRetryTests(unittest.IsolatedAsyncioTestCase):
    def test_retry_policy_constants(self):
        self.assertEqual(VOD_HTTP_RETRY_MAX_SECONDS, 30 * 60)
        self.assertEqual(VOD_RETRYABLE_HTTP_STATUSES, {429, 502, 503, 504})

    def test_http_status_parser(self):
        self.assertEqual(
            _http_status_from_exception(Exception("HTTP 503: Service Unavailable")),
            503,
        )
        self.assertEqual(
            _http_status_from_exception(Exception("HTTP 429: Too Many Requests")),
            429,
        )
        self.assertIsNone(_http_status_from_exception(Exception("connection reset")))

    async def test_vod_retries_retryable_http_statuses_with_backoff(self):
        manager = DownloadManager()
        manager._download_file_once = AsyncMock(
            side_effect=[
                Exception("HTTP 503: Service Unavailable"),
                Exception("HTTP 502: Bad Gateway"),
                Exception("HTTP 429: Too Many Requests"),
                1234,
            ]
        )
        manager._broadcast_log = AsyncMock()

        sleep_mock = AsyncMock()
        with patch("services.download_manager.asyncio.sleep", new=sleep_mock):
            result = await manager._download_file(
                "http://dispatcharr.test/proxy/vod/episode/1/session",
                "/tmp/mustarrd-vod-http-retry-test.mkv",
                10,
                object(),
                retry_http_errors=True,
            )

        self.assertEqual(result, 1234)
        self.assertEqual(manager._download_file_once.await_count, 4)
        self.assertEqual(
            sleep_mock.await_args_list,
            [call(15.0), call(30.0), call(60.0)],
        )
        self.assertEqual(manager._broadcast_log.await_count, 3)

    async def test_non_vod_503_still_fails_immediately(self):
        manager = DownloadManager()
        manager._download_file_once = AsyncMock(
            side_effect=Exception("HTTP 503: Service Unavailable")
        )
        manager._broadcast_log = AsyncMock()

        sleep_mock = AsyncMock()
        with patch("services.download_manager.asyncio.sleep", new=sleep_mock):
            with self.assertRaisesRegex(Exception, "HTTP 503"):
                await manager._download_file(
                    "http://provider.test/stream",
                    "/tmp/mustarrd-non-vod-http-retry-test.ts",
                    11,
                    object(),
                    retry_http_errors=False,
                )

        sleep_mock.assert_not_awaited()
        manager._broadcast_log.assert_not_awaited()

    async def test_permanent_vod_http_error_still_fails_immediately(self):
        manager = DownloadManager()
        manager._download_file_once = AsyncMock(
            side_effect=Exception("HTTP 404: Not Found")
        )
        manager._broadcast_log = AsyncMock()

        sleep_mock = AsyncMock()
        with patch("services.download_manager.asyncio.sleep", new=sleep_mock):
            with self.assertRaisesRegex(Exception, "HTTP 404"):
                await manager._download_file(
                    "http://dispatcharr.test/proxy/vod/episode/1/session",
                    "/tmp/mustarrd-vod-http-retry-404-test.mkv",
                    12,
                    object(),
                    retry_http_errors=True,
                )

        sleep_mock.assert_not_awaited()
        manager._broadcast_log.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
