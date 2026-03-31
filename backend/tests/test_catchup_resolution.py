import asyncio
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from models import AppSettings, EPGProgram, ScheduledRecording, XtreamAccount
from services.download_builder import build_download_from_program
from services.epg_service import epg_service
from services.xtream_client import XtreamClient


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class CatchupResolutionTests(unittest.TestCase):
    def test_timeshift_url_prefers_provider_token(self):
        client = XtreamClient("https://provider.example.com", "user", "pass")
        start_time = datetime(2026, 3, 30, 17, 0, tzinfo=timezone.utc)

        url = client.build_timeshift_url("123", start_time, 60, provider_start="2026-03-30:13-00")

        self.assertIn("/60/2026-03-30:13-00/123.ts", url)

    def test_serialize_program_includes_provider_tokens(self):
        row = EPGProgram(
            id=1,
            account_id=1,
            channel_id="123",
            channel_name="Test Channel",
            xmltv_id="xmltv-1",
            epg_id="123:100:200",
            title="Test Show",
            description="Desc",
            category="News",
            start_time=datetime(2026, 3, 30, 17, 0, tzinfo=timezone.utc),
            end_time=datetime(2026, 3, 30, 18, 0, tzinfo=timezone.utc),
            start_timestamp=1,
            stop_timestamp=2,
            provider_start="2026-03-30:13-00",
            provider_stop="2026-03-30:14-00",
            duration_minutes=60,
            has_archive=True,
        )

        payload = epg_service.serialize_program(row)

        self.assertEqual(payload["provider_start"], "2026-03-30:13-00")
        self.assertEqual(payload["provider_stop"], "2026-03-30:14-00")

    def test_serialize_program_uses_provider_slot_for_display(self):
        row = EPGProgram(
            id=1,
            account_id=1,
            channel_id="123",
            channel_name="Test Channel",
            xmltv_id="xmltv-1",
            epg_id="123:100:200",
            title="Test Show",
            description="Desc",
            category="News",
            start_time=datetime(2026, 3, 30, 17, 0, tzinfo=timezone.utc),
            end_time=datetime(2026, 3, 30, 18, 0, tzinfo=timezone.utc),
            start_timestamp=1,
            stop_timestamp=2,
            provider_start="2026-03-30:13-00",
            provider_stop="2026-03-30:14-00",
            duration_minutes=60,
            has_archive=True,
        )
        account = XtreamAccount(
            id=1,
            name="Provider A",
            server_url="https://provider.example.com",
            username="user",
            password="",
            catchup_resolution_mode="auto",
            catchup_fallback_offset_minutes=0,
        )

        payload = epg_service.serialize_program(row, account)

        self.assertEqual(payload["start_time"], "2026-03-30T13:00:00")
        self.assertEqual(payload["end_time"], "2026-03-30T14:00:00")

    def test_serialize_program_uses_account_fallback_for_display_without_provider_token(self):
        row = EPGProgram(
            id=1,
            account_id=1,
            channel_id="123",
            channel_name="Test Channel",
            xmltv_id="xmltv-1",
            epg_id="123:100:200",
            title="Test Show",
            description="Desc",
            category="News",
            start_time=datetime(2026, 3, 30, 17, 0, tzinfo=timezone.utc),
            end_time=datetime(2026, 3, 30, 18, 0, tzinfo=timezone.utc),
            start_timestamp=1,
            stop_timestamp=2,
            provider_start=None,
            provider_stop=None,
            duration_minutes=60,
            has_archive=True,
        )
        account = XtreamAccount(
            id=1,
            name="Provider B",
            server_url="https://provider.example.com",
            username="user",
            password="",
            catchup_resolution_mode="auto",
            catchup_fallback_offset_minutes=60,
        )

        payload = epg_service.serialize_program(row, account)

        self.assertTrue(payload["start_time"].endswith("18:00:00+00:00"))
        self.assertTrue(payload["end_time"].endswith("19:00:00+00:00"))

    def test_scheduled_recording_to_dict_includes_provider_tokens(self):
        row = ScheduledRecording(
            account_id=1,
            channel_id="123",
            channel_name="Test Channel",
            program_title="Test Show",
            program_description="Desc",
            program_start=datetime(2026, 3, 30, 17, 0, tzinfo=timezone.utc),
            program_end=datetime(2026, 3, 30, 18, 0, tzinfo=timezone.utc),
            start_timestamp=100,
            stop_timestamp=160,
            provider_start="2026-03-30:13-00",
            provider_stop="2026-03-30:14-00",
            duration_minutes=60,
        )

        payload = row.to_dict()

        self.assertEqual(payload["provider_start"], "2026-03-30:13-00")
        self.assertEqual(payload["provider_stop"], "2026-03-30:14-00")

    def test_auto_mode_uses_provider_token_when_present(self):
        download = asyncio.run(
            self._build_download(
                XtreamAccount(
                    id=1,
                    name="Provider A",
                    server_url="https://provider.example.com",
                    username="user",
                    password="",
                    catchup_resolution_mode="auto",
                    catchup_fallback_offset_minutes=60,
                ),
                {
                    "title": "Show",
                    "start_time": "2026-03-30T10:00:00+00:00",
                    "end_time": "2026-03-30T11:00:00+00:00",
                    "start_timestamp": 1774864800,
                    "stop_timestamp": 1774868400,
                    "provider_start": "2026-03-30:05-00",
                },
            )
        )

        self.assertIn("/60/2026-03-30:05-00/999.ts", download.source_url)

    def test_fallback_offset_applies_when_provider_token_missing(self):
        download = asyncio.run(
            self._build_download(
                XtreamAccount(
                    id=1,
                    name="Provider B",
                    server_url="https://provider.example.com",
                    username="user",
                    password="",
                    catchup_resolution_mode="auto",
                    catchup_fallback_offset_minutes=60,
                ),
                {
                    "title": "Show",
                    "start_time": "2026-03-30T10:00:00+00:00",
                    "end_time": "2026-03-30T11:00:00+00:00",
                    "start_timestamp": 1774864800,
                    "stop_timestamp": 1774868400,
                },
            )
        )

        self.assertIn("/60/2026-03-30:11-00/999.ts", download.source_url)

    def test_fallback_only_ignores_provider_token(self):
        download = asyncio.run(
            self._build_download(
                XtreamAccount(
                    id=1,
                    name="Provider C",
                    server_url="https://provider.example.com",
                    username="user",
                    password="",
                    catchup_resolution_mode="fallback_only",
                    catchup_fallback_offset_minutes=-60,
                ),
                {
                    "title": "Show",
                    "start_time": "2026-03-30T10:00:00+00:00",
                    "end_time": "2026-03-30T11:00:00+00:00",
                    "start_timestamp": 1774864800,
                    "stop_timestamp": 1774868400,
                    "provider_start": "2026-03-30:05-00",
                },
            )
        )

        self.assertIn("/60/2026-03-30:09-00/999.ts", download.source_url)

    def test_accounts_with_different_fallback_offsets_generate_different_urls(self):
        program = {
            "title": "Show",
            "start_time": "2026-03-30T10:00:00+00:00",
            "end_time": "2026-03-30T11:00:00+00:00",
            "start_timestamp": 1774864800,
            "stop_timestamp": 1774868400,
        }

        first = asyncio.run(
            self._build_download(
                XtreamAccount(
                    id=1,
                    name="Provider A",
                    server_url="https://provider.example.com",
                    username="user",
                    password="",
                    catchup_resolution_mode="auto",
                    catchup_fallback_offset_minutes=60,
                ),
                program,
            )
        )
        second = asyncio.run(
            self._build_download(
                XtreamAccount(
                    id=2,
                    name="Provider B",
                    server_url="https://provider.example.com",
                    username="user",
                    password="",
                    catchup_resolution_mode="auto",
                    catchup_fallback_offset_minutes=-240,
                ),
                program,
            )
        )

        self.assertNotEqual(first.source_url, second.source_url)
        self.assertIn("/2026-03-30:11-00/", first.source_url)
        self.assertIn("/2026-03-30:06-00/", second.source_url)

    def test_padding_applies_after_fallback_offset(self):
        download = asyncio.run(
            self._build_download(
                XtreamAccount(
                    id=1,
                    name="Provider D",
                    server_url="https://provider.example.com",
                    username="user",
                    password="",
                    catchup_resolution_mode="auto",
                    catchup_fallback_offset_minutes=60,
                ),
                {
                    "title": "Show",
                    "start_time": "2026-03-30T10:00:00+00:00",
                    "end_time": "2026-03-30T11:00:00+00:00",
                    "start_timestamp": 1774864800,
                    "stop_timestamp": 1774868400,
                },
                pre_padding=5,
                post_padding=10,
            )
        )

        self.assertIn("/75/2026-03-30:10-55/999.ts", download.source_url)

    async def _build_download(self, account, program, pre_padding=0, post_padding=0):
        session = AsyncMock()
        session.execute = AsyncMock(
            side_effect=[
                _ScalarResult(account),
                _ScalarResult(AppSettings(download_folder="/tmp")),
            ]
        )

        with patch("services.download_builder.resolve_account_password_with_migration", new=AsyncMock(return_value="pass")):
            with patch("services.download_builder.file_namer.generate_filename", return_value="test.ts"):
                with patch("services.download_builder.epg_service.detect_program_type", return_value="other"):
                    return await build_download_from_program(
                        session,
                        account_id=account.id,
                        channel_id="999",
                        channel_name="Test Channel",
                        program=program,
                        pre_padding_minutes=pre_padding,
                        post_padding_minutes=post_padding,
                    )


if __name__ == "__main__":
    unittest.main()
