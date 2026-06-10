import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.epg_ingest_manager import EPGIngestManager


class EPGStatusIntervalTests(unittest.TestCase):
    def test_status_reports_refresh_interval_hours(self):
        """The settings UI shows the refresh cadence from /api/epg/status."""
        manager = EPGIngestManager()
        status = manager.get_status()
        self.assertEqual(status["interval_hours"], manager._interval // 3600)
        self.assertGreaterEqual(status["interval_hours"], 1)


if __name__ == "__main__":
    unittest.main()
