import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from defusedxml import ElementTree as ET

from services.epg_ingest_manager import EPGIngestManager
from services.epg_metadata import extract_xmltv_metadata
from services.epg_service import EPGService


class StructuredXmltvMetadataTests(unittest.TestCase):
    def test_preserves_categories_episode_numbers_and_external_ids(self):
        elem = ET.fromstring(
            '<programme><title>Murder, She Wrote</title><sub-title>Final Curtain</sub-title>'
            '<category>Series</category><category>Mystery</category>'
            '<episode-num system="onscreen">S09E11</episode-num>'
            '<episode-num system="xmltv_ns">8.10.</episode-num>'
            '<episode-num system="dd_progid">EP00002995.0202</episode-num>'
            '<episode-num system="thetvdb.com">series/78049</episode-num>'
            '<episode-num system="themoviedb.org">series/484</episode-num>'
            '<episode-num system="imdb.com">tt0086765</episode-num></programme>'
        )
        metadata = extract_xmltv_metadata(elem)
        self.assertEqual(metadata["subtitle"], "Final Curtain")
        self.assertEqual(metadata["season_number"], 9)
        self.assertEqual(metadata["episode_number"], 11)
        self.assertIn('"Series"', metadata["categories_json"])
        self.assertIn('"Mystery"', metadata["categories_json"])
        self.assertEqual(metadata["dd_progid"], "EP00002995.0202")
        self.assertEqual(metadata["tvdb_id"], "series/78049")
        self.assertEqual(metadata["tmdb_id"], "series/484")
        self.assertEqual(metadata["imdb_id"], "tt0086765")

    def test_raw_unknown_xmltv_season_takes_precedence_over_onscreen_zero(self):
        elem = ET.fromstring(
            '<programme><episode-num system="onscreen">S00E158</episode-num>'
            '<episode-num system="xmltv_ns">-1.157.</episode-num></programme>'
        )
        metadata = extract_xmltv_metadata(elem)
        self.assertEqual(metadata["season_number"], 0)
        self.assertEqual(metadata["episode_number"], 158)
        self.assertEqual(metadata["episode_xmltv_ns"], "-1.157.")

    def test_iter_programs_emits_structured_columns(self):
        xmltv = (
            b'<tv><programme channel="guide.id" start="20260817010000 +0000" '
            b'stop="20260817020000 +0000"><title>Alice</title>'
            b'<sub-title>The Great Escape</sub-title><category>Series</category>'
            b'<category>Comedy</category><episode-num system="onscreen">S05E17</episode-num>'
            b'</programme></tv>'
        )
        manager = EPGIngestManager()
        maps = {
            "stream_by_xmltv_id": {"guide.id": ["3235"]},
            "stream_by_name": {},
            "stream_info": {
                "3235": {"name": "Antenna", "has_archive": True, "archive_days": 30}
            },
        }
        rows = list(
            manager._iter_programs(
                xmltv,
                maps,
                datetime(2026, 8, 17, tzinfo=timezone.utc),
            )
        )
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["channel_id"], "3235")
        self.assertEqual(row["subtitle"], "The Great Escape")
        self.assertEqual(row["season_number"], 5)
        self.assertEqual(row["episode_number"], 17)
        self.assertIn('"Comedy"', row["categories_json"])


class FreshEpgEnrichmentTests(unittest.TestCase):
    def setUp(self):
        self.service = EPGService()

    def test_requested_stream_id_wins_over_provider_xmltv_channel_id(self):
        account = SimpleNamespace(guide_offset_hours=0)
        result = self.service._process_epg_entry(
            {
                "channel_id": "guide.id",
                "start_timestamp": 1000,
                "stop_timestamp": 2000,
            },
            account,
            fallback_channel_id="3235",
        )
        self.assertEqual(result["channel_id"], "3235")
        self.assertEqual(result["epg_id"], "3235:1000:2000")

    def test_exact_live_row_inherits_only_missing_structured_metadata(self):
        live = [{
            "channel_id": "3235",
            "start_timestamp": 1000,
            "stop_timestamp": 2000,
            "title": "Alice",
            "description": "Fresh description",
            "has_archive": False,
        }]
        stored = [{
            "channel_id": "3235",
            "start_timestamp": 1000,
            "stop_timestamp": 2000,
            "title": "Alice stored",
            "description": "Stored description",
            "has_archive": True,
            "category": "Series",
            "categories": ["Series", "Comedy"],
            "subtitle": "The Great Escape",
            "season_number": 5,
            "episode_number": 17,
        }, {
            "channel_id": "3235",
            "start_timestamp": 3000,
            "stop_timestamp": 4000,
            "category": "Sports",
        }]
        result = self.service._enrich_live_programs(live, stored)
        self.assertEqual(len(result), 1, "stored-only rows must not widen fresh live results")
        self.assertEqual(result[0]["description"], "Fresh description")
        self.assertFalse(result[0]["has_archive"])
        self.assertEqual(result[0]["category"], "Series")
        self.assertEqual(result[0]["categories"], ["Series", "Comedy"])
        self.assertEqual(result[0]["subtitle"], "The Great Escape")
        self.assertEqual(result[0]["season_number"], 5)


if __name__ == "__main__":
    unittest.main()
