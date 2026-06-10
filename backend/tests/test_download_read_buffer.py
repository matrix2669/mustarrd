"""
Regression: downloads were several times slower than a plain wget of the same
provider URL.

Root cause: _download_file_once created its aiohttp.ClientSession with the
default 64KB read buffer. Each 1MB chunk awaits the disk write (plus periodic
DB commit and websocket broadcast); while the loop is busy, aiohttp flow
control stops reading the socket, the 64KB buffer fills, and the TCP receive
window collapses — capping throughput at roughly window/RTT on high-latency
provider links.

Fix: the download session is created with a large read_bufsize
(DOWNLOAD_READ_BUFFER_BYTES) so socket reads run ahead of disk writes.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.download_manager import DOWNLOAD_READ_BUFFER_BYTES, DownloadManager


def _make_response(chunks):
    response = MagicMock()
    response.status = 200
    response.content_length = sum(len(c) for c in chunks)
    response.reason = "OK"
    response.headers = {}

    async def iter_chunked(_size):
        for chunk in chunks:
            yield chunk

    response.content.iter_chunked = iter_chunked
    return response


def _make_client_session(response):
    get_cm = MagicMock()
    get_cm.__aenter__ = AsyncMock(return_value=response)
    get_cm.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.get.return_value = get_cm

    client_cm = MagicMock()
    client_cm.__aenter__ = AsyncMock(return_value=mock_session)
    client_cm.__aexit__ = AsyncMock(return_value=False)
    return client_cm


def _make_db_session():
    session = AsyncMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    return session


class DownloadReadBufferTests(unittest.IsolatedAsyncioTestCase):
    def test_buffer_is_much_larger_than_aiohttp_default(self):
        self.assertGreaterEqual(DOWNLOAD_READ_BUFFER_BYTES, 4 * 1024 * 1024)

    async def test_download_session_uses_large_read_buffer(self):
        body = b"\x47" * 256
        client_cm = _make_client_session(_make_response([body]))
        session_factory = MagicMock(return_value=client_cm)

        manager = DownloadManager()
        db_session = _make_db_session()

        with tempfile.NamedTemporaryFile(suffix=".ts", delete=False) as f:
            tmp_path = f.name

        try:
            with (
                patch("services.download_manager.aiohttp.ClientSession", session_factory),
                patch.object(manager, "_broadcast_log", AsyncMock()),
                patch.object(manager, "_broadcast_progress", AsyncMock()),
            ):
                total = await manager._download_file_once(
                    "http://provider/stream", tmp_path, 1, db_session, offset=0
                )

            self.assertEqual(total, 256)
            self.assertEqual(session_factory.call_count, 1)
            self.assertEqual(
                session_factory.call_args.kwargs.get("read_bufsize"),
                DOWNLOAD_READ_BUFFER_BYTES,
                "The download ClientSession must override aiohttp's 64KB "
                "default read buffer, or TCP flow control throttles transfers.",
            )
        finally:
            os.unlink(tmp_path)


if __name__ == "__main__":
    unittest.main()
