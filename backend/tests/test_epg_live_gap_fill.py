"""
Seam coverage for issue #421 step 2: a sparse live guide response is filled in
from the stored guide entry for the same airing.

Browse prefers the provider's live guide endpoint, which many providers answer
with title and timing only. The same program read through stored guide results
or search carries a category, a subtitle, a season and episode, and external
identifiers. That made Browse the worst view of the guide.

An XMLTV document goes through ingest into a temporary SQLite database, then the
guide is read the way Browse reads it (prefer_live) against a provider that
returns a bare entry. Everything asserted here is what a guide consumer sees:
the returned program payload.
"""
import base64
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import models  # noqa: F401  (registers every table on Base.metadata)
from database import Base
from models import AppSettings, XtreamAccount
from services.epg_ingest_manager import EPGIngestManager, _program_insert_stmt
from services.epg_service import EPGService

ACCOUNT_ID = 1
CHANNEL_ID = "101"
CHANNELS = [{"stream_id": CHANNEL_ID, "name": "CNN", "tv_archive": 1, "tv_archive_duration": 7}]

# Yesterday, so the airing stays inside the catchup window the guide asks for.
START = (datetime.now(timezone.utc) - timedelta(days=1)).replace(
    minute=0, second=0, microsecond=0
)
STOP = START + timedelta(hours=1)

FULL_PROGRAMME = (
    "<sub-title>The Situation Room</sub-title>"
    "<category>Series</category><category>Talk</category>"
    '<episode-num system="onscreen">S03E07</episode-num>'
    '<episode-num system="thetvdb.com">series/12345</episode-num>'
)


def _xmltv(programme_body: str, start=START, stop=STOP) -> bytes:
    fmt = "%Y%m%d%H%M%S +0000"
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<tv>"
        '<channel id="cnn.us"><display-name>CNN</display-name></channel>'
        f'<programme start="{start.strftime(fmt)}" stop="{stop.strftime(fmt)}" channel="cnn.us">'
        "<title>Newsroom</title>"
        "<desc>Stored description</desc>"
        f"{programme_body}"
        "</programme>"
        "</tv>"
    ).encode("utf-8")


def _b64(value: str) -> str:
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


def _live_entry(**overrides) -> dict:
    """What a bare provider live guide answers with: title and timing, nothing else."""
    entry = {
        "id": "9001",
        "epg_id": "9001",
        "channel_id": CHANNEL_ID,
        "title": _b64("Newsroom Live"),
        "description": _b64("Live description"),
        "start_timestamp": int(START.timestamp()),
        "stop_timestamp": int(STOP.timestamp()),
        "start": START.strftime("%Y-%m-%d %H:%M:%S"),
        "stop": STOP.strftime("%Y-%m-%d %H:%M:%S"),
        "has_archive": 1,
    }
    entry.update(overrides)
    return entry


class LiveGuideGapFillTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.session_maker = async_sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )
        async with self.session_maker() as session:
            async with session.begin():
                session.add(
                    XtreamAccount(
                        id=ACCOUNT_ID,
                        name="Test",
                        server_url="http://example.com",
                        username="user",
                        password="pass",
                        guide_offset_hours=0,
                    )
                )
                session.add(AppSettings(id=1))
        self.manager = EPGIngestManager()

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def _ingest(self, programme_body: str, start=START, stop=STOP):
        maps = self.manager._build_channel_maps(CHANNELS)
        rows = [
            dict(row, account_id=ACCOUNT_ID)
            for row in self.manager._iter_programs(
                _xmltv(programme_body, start, stop), maps, datetime.now(timezone.utc)
            )
        ]
        self.assertTrue(rows, "fixture produced no programs")
        async with self.session_maker() as session:
            async with session.begin():
                await session.execute(_program_insert_stmt(), rows)

    async def _browse(self, entries) -> list:
        """Read the guide the way Browse does: live response preferred."""
        client = MagicMock()
        client.get_epg = AsyncMock(return_value=entries)
        client.close = AsyncMock()
        service = EPGService()
        async with self.session_maker() as session:
            with (
                patch("services.epg_service.XtreamClient", return_value=client),
                patch(
                    "services.epg_service.resolve_account_password_with_migration",
                    AsyncMock(return_value="pass"),
                ),
            ):
                return await service.get_epg_for_channel(
                    session,
                    ACCOUNT_ID,
                    CHANNEL_ID,
                    use_cache=False,
                    prefer_live=True,
                    archive_days=7,
                )

    async def _browse_one(self, entries=None) -> dict:
        programs = await self._browse(entries if entries is not None else [_live_entry()])
        self.assertEqual(len(programs), 1)
        return programs[0]

    async def test_sparse_live_entry_gains_the_stored_metadata(self):
        await self._ingest(FULL_PROGRAMME)

        program = await self._browse_one()

        self.assertEqual(program["category"], "Series")
        self.assertEqual(program["categories"], ["Series", "Talk"])
        self.assertEqual(program["subtitle"], "The Situation Room")
        self.assertEqual(program["season_number"], 3)
        self.assertEqual(program["episode_number"], 7)
        self.assertEqual(program["tvdb_id"], "series/12345")

    async def test_live_entry_with_no_stored_match_is_unchanged(self):
        """A different airing must not lend its metadata."""
        await self._ingest(FULL_PROGRAMME, start=START + timedelta(hours=2),
                           stop=STOP + timedelta(hours=2))

        program = await self._browse_one()

        self.assertIsNone(program["category"])
        self.assertIsNone(program["subtitle"])
        self.assertIsNone(program["season_number"])

    async def test_requested_channel_id_wins_over_provider_channel_id(self):
        await self._ingest(FULL_PROGRAMME)

        program = await self._browse_one([_live_entry(channel_id="999")])

        self.assertEqual(program["channel_id"], CHANNEL_ID)
        self.assertEqual(program["subtitle"], "The Situation Room")

    def test_provider_channel_id_is_used_without_an_explicit_request_id(self):
        program = EPGService()._process_epg_entry(
            _live_entry(channel_id="999")
        )

        self.assertEqual(program["channel_id"], "999")

    async def test_a_stored_row_ending_at_a_different_time_does_not_match(self):
        await self._ingest(FULL_PROGRAMME, stop=STOP + timedelta(minutes=30))

        program = await self._browse_one()

        self.assertIsNone(program["subtitle"])

    async def test_live_title_description_and_timing_stay_authoritative(self):
        await self._ingest(FULL_PROGRAMME)

        program = await self._browse_one()

        self.assertEqual(program["title"], "Newsroom Live")
        self.assertEqual(program["description"], "Live description")
        self.assertEqual(program["start_timestamp"], int(START.timestamp()))
        self.assertEqual(program["stop_timestamp"], int(STOP.timestamp()))
        self.assertEqual(program["start_time"], START.isoformat())
        self.assertEqual(program["end_time"], STOP.isoformat())

    async def test_metadata_the_live_entry_supplies_is_not_overwritten(self):
        """Only gaps are filled: anything the provider sent wins."""
        await self._ingest(FULL_PROGRAMME)

        program = await self._browse_one(
            [_live_entry(subtitle="Tonight", season=9, episode=1)]
        )

        self.assertEqual(program["subtitle"], "Tonight")
        self.assertEqual(program["season_number"], 9)
        self.assertEqual(program["episode_number"], 1)
        self.assertEqual(program["categories"], ["Series", "Talk"])

    async def test_live_archive_availability_stays_authoritative(self):
        """The provider says this airing is gone; the stored row must not revive it."""
        await self._ingest(FULL_PROGRAMME)

        program = await self._browse_one([_live_entry(has_archive=0)])

        self.assertFalse(program["has_archive"])
        self.assertEqual(program["subtitle"], "The Situation Room")

    async def test_a_category_the_live_entry_supplies_is_not_overwritten(self):
        await self._ingest(FULL_PROGRAMME)

        program = await self._browse_one([_live_entry(category="Live News")])

        self.assertEqual(program["category"], "Live News")
        self.assertEqual(program["categories"], ["Live News"])
        self.assertEqual(program["subtitle"], "The Situation Room")

    async def test_browse_and_the_stored_read_agree_about_the_same_airing(self):
        await self._ingest(FULL_PROGRAMME)

        live = await self._browse_one()
        stored_programs = await self._browse([])  # no live data: falls back to storage
        self.assertEqual(len(stored_programs), 1)
        stored = stored_programs[0]

        for key in ("category", "categories", "subtitle", "season_number",
                    "episode_number", "tvdb_id"):
            self.assertEqual(live[key], stored[key], key)


if __name__ == "__main__":
    unittest.main()
