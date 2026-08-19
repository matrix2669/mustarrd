import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.epg_targeted_diagnostics import (  # noqa: E402
    _closest,
    _parse_xmltv_start,
    _resolve_targets,
    _structured_row_snapshot,
)


class TargetedEPGDiagnosticsTests(unittest.TestCase):
    def test_resolves_exact_stream_id(self):
        provider = [
            {"stream_id": 3304, "name": "YES Network"},
            {"stream_id": 3305, "name": "Next Level Sports"},
        ]
        selected, ambiguous, unmatched = _resolve_targets(["3304"], provider, [])
        self.assertEqual([str(item["stream_id"]) for item in selected], ["3304"])
        self.assertEqual(ambiguous, [])
        self.assertEqual(unmatched, [])

    def test_resolves_case_insensitive_channel_name(self):
        provider = [{"stream_id": 3304, "name": "YES Network"}]
        selected, ambiguous, unmatched = _resolve_targets([" yes network "], provider, [])
        self.assertEqual([str(item["stream_id"]) for item in selected], ["3304"])
        self.assertEqual(ambiguous, [])
        self.assertEqual(unmatched, [])

    def test_ambiguous_partial_name_is_reported(self):
        provider = [
            {"stream_id": 1, "name": "HBO East"},
            {"stream_id": 2, "name": "HBO Zone East"},
        ]
        selected, ambiguous, unmatched = _resolve_targets(["HBO"], provider, [])
        self.assertEqual(selected, [])
        self.assertEqual(unmatched, [])
        self.assertEqual(ambiguous[0]["requested"], "HBO")
        self.assertEqual(len(ambiguous[0]["matches"]), 2)

    def test_xmltv_timestamp_parsing(self):
        parsed = _parse_xmltv_start("20260811183000 +0000")
        self.assertEqual(parsed, datetime(2026, 8, 11, 18, 30, tzinfo=timezone.utc))

    def test_closest_samples_near_now(self):
        now = datetime.now(timezone.utc)
        items = [
            {"when": now.replace(hour=max(0, now.hour - 4))},
            {"when": now},
            {"when": now.replace(hour=min(23, now.hour + 4))},
        ]
        selected = _closest(items, 1, lambda item: item["when"])
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["when"], now)

    def test_structured_row_snapshot_includes_optional_fields(self):
        row = SimpleNamespace(
            id=1,
            account_id=1,
            channel_id="3304",
            channel_name="YES Network",
            xmltv_id="576",
            epg_id="3304:1:2",
            title="Yankeeography",
            description="Biography series",
            category="Sports",
            start_time=datetime(2026, 8, 11, 12, 0),
            end_time=datetime(2026, 8, 11, 13, 0),
            start_timestamp=1,
            stop_timestamp=2,
            provider_start="2026-08-11:12-00",
            provider_stop="2026-08-11:13-00",
            duration_minutes=60,
            has_archive=True,
            created_at=datetime(2026, 8, 11, 12, 0),
            subtitle="Episode One",
            categories_json='["Sports", "Series"]',
            season_number=1,
            episode_number=1,
            episode_onscreen="S01E01",
            episode_xmltv_ns="0.0.",
            dd_progid="EP123.0001",
            tvdb_id="series/123",
            tmdb_id="series/456",
            imdb_id="tt1234567",
        )
        snapshot = _structured_row_snapshot(row)
        self.assertEqual(snapshot["subtitle"], "Episode One")
        self.assertEqual(snapshot["categories"], ["Sports", "Series"])
        self.assertEqual(snapshot["season_number"], 1)
        self.assertEqual(snapshot["episode_number"], 1)
        self.assertEqual(snapshot["dd_progid"], "EP123.0001")


if __name__ == "__main__":
    unittest.main()
