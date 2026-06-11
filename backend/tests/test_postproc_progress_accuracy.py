"""
Regression tests for post-processing progress accuracy.

Bug 1: remove_commercials used a fixed 40/60 progress split between segment
       extraction (fast stream copy) and concat encode (slow), with equal
       per-segment steps regardless of segment length. The bar raced to 40%
       then crawled. _plan_commercial_removal_progress now weights both
       phases by expected wall time.

Bug 2: _run_ffmpeg_with_progress trusted the ffprobe duration and reported
       100% mid-encode when the duration was underestimated (common for IPTV
       TS streams). Progress now holds below 100 until ffmpeg actually exits.

Bug 3: a persisted hw_accel setting (e.g. VideoToolbox) was used even when
       the encoder is unavailable on the current platform (e.g. running in
       Docker on a Mac). resolve_hw_accel falls back to CPU with a warning.
"""
import asyncio
import importlib.util
import os
import stat
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "services" / "post_processor.py"
SPEC = importlib.util.spec_from_file_location("post_processor_progress_test", MODULE_PATH)
POST_PROCESSOR_MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(POST_PROCESSOR_MODULE)

PostProcessor = POST_PROCESSOR_MODULE.PostProcessor
HardwareAccel = POST_PROCESSOR_MODULE.HardwareAccel


class CommercialRemovalProgressPlanTests(unittest.TestCase):
    """Bug 1: phase weighting for commercial-removal progress."""

    def setUp(self):
        self.processor = PostProcessor()
        self.duration = 3600.0
        # Two keep segments: 0-1500 and 1800-3600 (kept = 3300s).
        self.keep_segments = [(0.0, 1500.0), (1800.0, 3600.0)]

    def test_extract_costs_scale_with_segment_end_position(self):
        """Extraction demuxes from t=0 to each segment end, so cost = end."""
        costs, _ = self.processor._plan_commercial_removal_progress(
            self.keep_segments, self.duration, remux_only=False
        )
        self.assertEqual(costs, [1500.0, 3600.0])

    def test_transcode_gives_most_of_bar_to_concat_encode(self):
        """Re-encoding dominates wall time; extraction share must be small."""
        _, share = self.processor._plan_commercial_removal_progress(
            self.keep_segments, self.duration, remux_only=False
        )
        self.assertLess(share, 30.0)
        self.assertGreater(share, 0.0)

    def test_remux_share_larger_than_transcode_share(self):
        """With stream-copy concat, extraction is a bigger fraction of the work."""
        _, transcode_share = self.processor._plan_commercial_removal_progress(
            self.keep_segments, self.duration, remux_only=False
        )
        _, remux_share = self.processor._plan_commercial_removal_progress(
            self.keep_segments, self.duration, remux_only=True
        )
        self.assertGreater(remux_share, transcode_share)

    def test_open_ended_segment_costs_full_duration(self):
        """A segment with end <= start runs to EOF; cost is the full duration."""
        costs, _ = self.processor._plan_commercial_removal_progress(
            [(120.0, 0.0)], self.duration, remux_only=False
        )
        self.assertEqual(costs, [3600.0])

    def test_empty_segments_do_not_crash(self):
        costs, share = self.processor._plan_commercial_removal_progress(
            [], self.duration, remux_only=False
        )
        self.assertEqual(costs, [])
        self.assertEqual(share, 50.0)


class FfmpegProgressCapTests(unittest.TestCase):
    """Bug 2: progress must hold below 100 until ffmpeg exits."""

    def setUp(self):
        self.processor = PostProcessor()
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.tmp)

    def _fake_ffmpeg(self, body: str) -> str:
        path = Path(self.tmp) / "fake_ffmpeg.sh"
        path.write_text(f"#!/bin/sh\n{body}\n")
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
        return str(path)

    def test_out_time_past_duration_capped_below_100_until_exit(self):
        """out_time beyond the probed duration must not report 100 mid-run."""
        script = self._fake_ffmpeg(
            'echo "out_time=00:00:30.000000"\n'
            'echo "progress=continue"\n'
            'echo "out_time=00:01:00.000000"\n'
            'echo "progress=end"\n'
            "exit 0"
        )
        reported = []

        async def run():
            returncode, _ = await self.processor._run_ffmpeg_with_progress(
                [script], duration=10.0, progress_callback=reported.append
            )
            return returncode

        returncode = asyncio.run(run())
        self.assertEqual(returncode, 0)
        self.assertTrue(reported, "expected progress updates")
        self.assertEqual(reported[-1], 100.0, "clean exit must report 100")
        for value in reported[:-1]:
            self.assertLessEqual(
                value, 99.0,
                f"mid-run progress {value} exceeded the pre-exit cap"
            )


class ResolveHwAccelTests(unittest.TestCase):
    """Bug 3: unavailable hardware encoder must fall back to CPU."""

    def setUp(self):
        self.processor = PostProcessor()

    def test_cpu_passes_through_without_probing_encoders(self):
        def boom():
            raise AssertionError("CPU must not trigger encoder detection")
        self.processor.get_available_hardware_accels = boom

        accel, warning = self.processor.resolve_hw_accel(HardwareAccel.CPU)
        self.assertEqual(accel, HardwareAccel.CPU)
        self.assertIsNone(warning)

    def test_unavailable_videotoolbox_falls_back_to_cpu_with_warning(self):
        self.processor.get_available_hardware_accels = lambda: [
            {"id": "cpu", "available": True},
        ]
        accel, warning = self.processor.resolve_hw_accel(HardwareAccel.APPLE_SILICON)
        self.assertEqual(accel, HardwareAccel.CPU)
        self.assertIsNotNone(warning)
        self.assertIn("videotoolbox", warning)
        self.assertIn("CPU", warning)

    def test_available_accel_is_kept(self):
        self.processor.get_available_hardware_accels = lambda: [
            {"id": "cpu", "available": True},
            {"id": "videotoolbox", "available": True},
        ]
        accel, warning = self.processor.resolve_hw_accel(HardwareAccel.APPLE_SILICON)
        self.assertEqual(accel, HardwareAccel.APPLE_SILICON)
        self.assertIsNone(warning)


if __name__ == "__main__":
    unittest.main()
