"""
Seam coverage for issue #421 step 1: XMLTV ingest -> storage -> guide read-back.

An XMLTV document goes through the ingest parser, the rows are upserted into a
temporary SQLite database exactly as a refresh does, and the programs are read
back the way the guide reads them. Everything asserted here is something a guide
consumer can observe: the serialized program payload.
"""
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import models  # noqa: F401  (registers every table on Base.metadata)
from database import Base, _apply_lightweight_migrations, _column_exists
from guide_metadata import GuideMetadata
from models import EPGProgram
from services.epg_ingest_manager import EPGIngestManager, _program_insert_stmt
from services.epg_service import epg_service

ACCOUNT_ID = 1
CHANNELS = [{"stream_id": "101", "name": "CNN", "tv_archive": 1, "tv_archive_duration": 7}]
NOW = datetime(2026, 6, 9, 12, 0, 0, tzinfo=timezone.utc)


def _xmltv(programme_body: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<tv>"
        '<channel id="cnn.us"><display-name>CNN</display-name></channel>'
        '<programme start="20260608120000 +0000" stop="20260608130000 +0000" channel="cnn.us">'
        "<title>Newsroom</title>"
        f"{programme_body}"
        "</programme>"
        "</tv>"
    ).encode("utf-8")


class MetadataIngestTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.session_maker = async_sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )
        self.manager = EPGIngestManager()

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def _ingest(self, programme_body: str):
        maps = self.manager._build_channel_maps(CHANNELS)
        rows = [
            dict(row, account_id=ACCOUNT_ID)
            for row in self.manager._iter_programs(_xmltv(programme_body), maps, NOW)
        ]
        self.assertTrue(rows, "fixture produced no programs")
        async with self.session_maker() as session:
            async with session.begin():
                await session.execute(_program_insert_stmt(), rows)

    async def _read_back(self) -> dict:
        async with self.session_maker() as session:
            result = await session.execute(
                select(EPGProgram).where(EPGProgram.account_id == ACCOUNT_ID)
            )
            rows = result.scalars().all()
        self.assertEqual(len(rows), 1)
        return epg_service.serialize_program(rows[0])

    async def test_every_category_is_kept_and_the_first_stays_in_category(self):
        await self._ingest(
            "<category>Series</category><category>Talk</category><category>Sports</category>"
        )

        program = await self._read_back()

        self.assertEqual(program["categories"], ["Series", "Talk", "Sports"])
        self.assertEqual(program["category"], "Series")

    async def test_duplicate_and_blank_categories_collapsed(self):
        await self._ingest(
            "<category>Sports</category><category> </category><category>sports</category>"
        )

        program = await self._read_back()

        self.assertEqual(program["categories"], ["Sports"])

    async def test_subtitle_preserved(self):
        await self._ingest("<sub-title>The Situation Room</sub-title>")

        self.assertEqual((await self._read_back())["subtitle"], "The Situation Room")

    async def test_season_and_episode_from_the_onscreen_form(self):
        await self._ingest('<episode-num system="onscreen">S03E07</episode-num>')

        program = await self._read_back()

        self.assertEqual(program["season_number"], 3)
        self.assertEqual(program["episode_number"], 7)
        self.assertEqual(program["episode_num_onscreen"], "S03E07")

    async def test_season_and_episode_from_the_xmltv_form_are_converted(self):
        await self._ingest('<episode-num system="xmltv_ns">2 . 4 . 0/1</episode-num>')

        program = await self._read_back()

        self.assertEqual(program["season_number"], 3)
        self.assertEqual(program["episode_number"], 5)
        self.assertEqual(program["episode_num_xmltv"], "2 . 4 . 0/1")

    async def test_onscreen_form_wins_when_both_are_present(self):
        await self._ingest(
            '<episode-num system="onscreen">S03E07</episode-num>'
            '<episode-num system="xmltv_ns">8 . 8 . 0/1</episode-num>'
        )

        program = await self._read_back()

        self.assertEqual((program["season_number"], program["episode_number"]), (3, 7))

    async def test_malformed_episode_numbers_do_not_break_the_refresh(self):
        await self._ingest('<episode-num system="xmltv_ns">who . knows</episode-num>')

        program = await self._read_back()

        self.assertEqual(program["title"], "Newsroom")
        self.assertIsNone(program["season_number"])
        self.assertIsNone(program["episode_number"])

    async def test_external_identifiers_stored(self):
        await self._ingest(
            '<episode-num system="dd_progid">EP012345670001</episode-num>'
            '<episode-num system="thetvdb.com">series/71663</episode-num>'
            '<episode-num system="themoviedb.org">movie/603</episode-num>'
            '<episode-num system="imdb.com">tt0133093</episode-num>'
        )

        program = await self._read_back()

        self.assertEqual(program["gracenote_id"], "EP012345670001")
        self.assertEqual(program["tvdb_id"], "series/71663")
        self.assertEqual(program["tmdb_id"], "movie/603")
        self.assertEqual(program["imdb_id"], "tt0133093")

    async def test_a_refresh_that_supplies_a_value_overwrites_the_stored_one(self):
        await self._ingest("<category>Sports</category><sub-title>Wrong</sub-title>")
        await self._ingest("<category>News</category><sub-title>Right</sub-title>")

        program = await self._read_back()

        self.assertEqual(program["category"], "News")
        self.assertEqual(program["categories"], ["News"])
        self.assertEqual(program["subtitle"], "Right")

    async def test_a_refresh_that_omits_a_field_leaves_the_stored_value_alone(self):
        await self._ingest(
            "<category>News</category>"
            "<sub-title>The Situation Room</sub-title>"
            '<episode-num system="onscreen">S03E07</episode-num>'
        )
        await self._ingest("")

        program = await self._read_back()

        self.assertEqual(program["category"], "News")
        self.assertEqual(program["categories"], ["News"])
        self.assertEqual(program["subtitle"], "The Situation Room")
        self.assertEqual((program["season_number"], program["episode_number"]), (3, 7))

    async def test_a_program_without_metadata_reads_back_with_empty_fields(self):
        await self._ingest("")

        program = await self._read_back()

        self.assertEqual(program["categories"], [])
        self.assertIsNone(program["category"])
        self.assertIsNone(program["subtitle"])
        self.assertIsNone(program["season_number"])


class MetadataMigrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_an_older_database_gains_the_metadata_columns_on_startup(self):
        engine = create_async_engine("sqlite+aiosqlite://")
        legacy_tables = [
            "plex_servers",
            "app_settings",
            "epg_programs",
            "xtream_accounts",
            "scheduled_recordings",
            "downloads",
        ]
        try:
            async with engine.begin() as conn:
                for table in legacy_tables:
                    await conn.execute(text(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)"))
                await _apply_lightweight_migrations(conn)

                for column in GuideMetadata.NEW_COLUMN_NAMES:
                    self.assertTrue(
                        await _column_exists(conn, "epg_programs", column),
                        f"epg_programs is missing {column} after migration",
                    )
        finally:
            await engine.dispose()

    async def test_migration_covers_every_new_field(self):
        """The migration is driven by the same field list as the model."""
        model_columns = {c.name for c in EPGProgram.__table__.columns}
        self.assertTrue(set(GuideMetadata.COLUMN_NAMES) <= model_columns)


if __name__ == "__main__":
    unittest.main()
