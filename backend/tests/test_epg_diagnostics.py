import sys
import unittest
from pathlib import Path

from defusedxml import ElementTree as ET

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.epg_diagnostics import (
    _Reservoir,
    _classification_snapshot,
    _provider_channel_snapshot,
    _scrub_value,
    _select_evenly,
    _xmltv_program_snapshot,
)


class EpgDiagnosticsHelpersTests(unittest.TestCase):
    def test_xmltv_snapshot_preserves_structured_and_unknown_metadata(self):
        elem = ET.fromstring(
            """
            <programme channel="station-1" start="20260811120000 -0400" stop="20260811123000 -0400">
              <title lang="en">Example Show</title>
              <sub-title lang="en">The Test Episode</sub-title>
              <desc>Episode description</desc>
              <category>Comedy</category>
              <category>Series</category>
              <episode-num system="xmltv_ns">7.22.</episode-num>
              <episode-num system="onscreen">S08E23</episode-num>
              <date>1997</date>
              <previously-shown start="20200101000000 +0000" />
              <credits><actor>Example Actor</actor></credits>
              <url>https://provider.example/user/pass/program</url>
            </programme>
            """
        )

        snapshot = _xmltv_program_snapshot(
            elem,
            ["https://provider.example", "user", "pass"],
        )

        self.assertEqual(snapshot["source"], "xmltv_raw")
        self.assertEqual(snapshot["children"]["category"][0]["text"], "Comedy")
        self.assertEqual(snapshot["children"]["category"][1]["text"], "Series")
        self.assertEqual(
            snapshot["children"]["episode-num"][1]["attributes"]["system"],
            "onscreen",
        )
        self.assertEqual(snapshot["children"]["sub-title"][0]["text"], "The Test Episode")
        self.assertIn("credits", snapshot["children"])
        self.assertIn("episode-num", snapshot["raw_xml"])
        self.assertNotIn("https://provider.example", snapshot["raw_xml"])
        self.assertNotIn("/user/pass/", snapshot["raw_xml"])

    def test_scrubber_removes_credentials_but_keeps_unknown_fields(self):
        value = {
            "username": "demo-user",
            "password": "demo-pass",
            "mystery_metadata": "value demo-pass",
            "nested": {"token": "abc", "classification_hint": "series"},
        }

        scrubbed = _scrub_value(value, ["demo-user", "demo-pass"])

        self.assertEqual(scrubbed["username"], "[REDACTED]")
        self.assertEqual(scrubbed["password"], "[REDACTED]")
        self.assertEqual(scrubbed["mystery_metadata"], "value [REDACTED]")
        self.assertEqual(scrubbed["nested"]["token"], "[REDACTED]")
        self.assertEqual(scrubbed["nested"]["classification_hint"], "series")

    def test_provider_channel_snapshot_whitelists_values_and_reports_extra_fields(self):
        channel = {
            "stream_id": 123,
            "name": "Example HD",
            "category_id": "9",
            "epg_channel_id": "example.station",
            "tv_archive": 1,
            "tv_archive_duration": 7,
            "direct_source": "https://provider.example/user/pass/123.ts",
            "unexpected_hint": "series-heavy",
        }

        snapshot = _provider_channel_snapshot(
            channel,
            {"9": "Entertainment"},
            ["https://provider.example", "user", "pass"],
        )

        self.assertEqual(snapshot["category_name"], "Entertainment")
        self.assertNotIn("direct_source", snapshot)
        self.assertIn("direct_source", snapshot["extra_field_names"])
        self.assertIn("unexpected_hint", snapshot["extra_field_names"])

    def test_even_sampling_covers_source_instead_of_only_head(self):
        result = _select_evenly(list(range(100)), 4)
        self.assertEqual(len(result), 4)
        self.assertGreater(result[-1], 80)
        self.assertLess(result[0], 20)

    def test_reservoir_is_bounded_and_deterministic(self):
        first = _Reservoir(5, "same-seed")
        second = _Reservoir(5, "same-seed")
        for value in range(100):
            first.add(value)
            second.add(value)

        self.assertEqual(first.seen, 100)
        self.assertEqual(len(first.items), 5)
        self.assertEqual(first.items, second.items)

    def test_classification_snapshot_records_current_classifier_inputs(self):
        snapshot = _classification_snapshot(
            {
                "title": "Example Show S02E05 - Testing",
                "description": "Description",
                "category": "Comedy",
                "channel_id": "123",
            },
            "Example Channel",
        )

        self.assertEqual(snapshot["result"], "tv_show")
        self.assertEqual(snapshot["inputs"]["category"], "Comedy")
        self.assertEqual(snapshot["inputs"]["channel_name"], "Example Channel")


if __name__ == "__main__":
    unittest.main()
