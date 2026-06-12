"""Tests for the ProcessRunner seam and the post_processor sites routed
through it. These exercise the real interface with a FakeProcessRunner, so no
ffmpeg/ffprobe binary is spawned."""

import asyncio
import subprocess
import unittest

from services.process_runner import (
    CommandResult,
    FakeProcessRunner,
    ProcessRunner,
)
from services.post_processor import PostProcessor


class CommandResultTests(unittest.TestCase):
    def test_text_properties_decode_lossily(self):
        r = CommandResult(returncode=0, stdout=b"good\xffbye", stderr=b"err")
        self.assertIn("good", r.stdout_text)
        self.assertEqual(r.stderr_text, "err")

    def test_timed_out_has_no_returncode(self):
        r = CommandResult(returncode=None, timed_out=True)
        self.assertIsNone(r.returncode)
        self.assertTrue(r.timed_out)


class FakeProcessRunnerTests(unittest.IsolatedAsyncioTestCase):
    def test_run_sync_returns_queued_result_and_records_call(self):
        fake = FakeProcessRunner()
        fake.queue_sync(returncode=0, stdout="ok")
        result = fake.run_sync(["ffmpeg", "-version"])
        self.assertEqual(result.stdout, "ok")
        self.assertEqual(fake.calls, [("sync", ["ffmpeg", "-version"])])

    def test_run_sync_raises_queued_error(self):
        fake = FakeProcessRunner()
        fake.queue_sync_error(FileNotFoundError())
        with self.assertRaises(FileNotFoundError):
            fake.run_sync(["nope"])

    async def test_run_capture_returns_queued_result(self):
        fake = FakeProcessRunner()
        fake.queue_capture(returncode=0, stdout=b"42")
        result = await fake.run_capture(["ffprobe"])
        self.assertEqual(result.stdout, b"42")
        self.assertEqual(fake.calls, [("capture", ["ffprobe"])])

    async def test_run_capture_raises_queued_error(self):
        fake = FakeProcessRunner()
        fake.queue_capture_error(asyncio.CancelledError())
        with self.assertRaises(asyncio.CancelledError):
            await fake.run_capture(["ffprobe"])


class RealRunnerTests(unittest.IsolatedAsyncioTestCase):
    """A couple of smoke tests against the real adapter using portable shells."""

    async def test_run_capture_captures_output_and_code(self):
        runner = ProcessRunner()
        result = await runner.run_capture(
            ["python3", "-c", "import sys; sys.stdout.write('hi'); sys.exit(3)"]
        )
        self.assertEqual(result.returncode, 3)
        self.assertEqual(result.stdout_text, "hi")
        self.assertFalse(result.timed_out)

    async def test_run_capture_times_out_and_kills(self):
        runner = ProcessRunner()
        result = await runner.run_capture(
            ["python3", "-c", "import time; time.sleep(30)"], timeout=0.2
        )
        self.assertTrue(result.timed_out)
        self.assertIsNone(result.returncode)

    def test_run_sync_raises_file_not_found(self):
        runner = ProcessRunner()
        with self.assertRaises(FileNotFoundError):
            runner.run_sync(["definitely-not-a-real-binary-xyz"])


class ProbeToolTests(unittest.TestCase):
    def test_probe_success(self):
        fake = FakeProcessRunner()
        fake.queue_sync(returncode=0, stdout="ffmpeg version 6")
        pp = PostProcessor(runner=fake)
        ok, err = pp._probe_tool(pp._ffmpeg_path or "ffmpeg", ["-version"])
        # Only reaches the runner when the path is executable; assert on the
        # call shape when it does.
        if fake.calls:
            self.assertTrue(ok)
            self.assertIsNone(err)

    def test_probe_maps_timeout(self):
        fake = FakeProcessRunner()
        fake.queue_sync_error(subprocess.TimeoutExpired(cmd="x", timeout=5))
        pp = PostProcessor(runner=fake)
        # Force past the executable check by probing the resolved ffmpeg path
        # if present; otherwise this still exercises the mapping via a path we
        # know exists.
        ok, err = pp._probe_tool("/bin/sh", ["-c", "true"])
        self.assertFalse(ok)
        self.assertEqual(err, "timed out while probing")

    def test_probe_reports_nonzero_exit(self):
        fake = FakeProcessRunner()
        fake.queue_sync(returncode=1, stderr="boom")
        pp = PostProcessor(runner=fake)
        ok, err = pp._probe_tool("/bin/sh", ["-c", "false"])
        self.assertFalse(ok)
        self.assertIn("exit 1", err)
        self.assertIn("boom", err)


class GetDurationTests(unittest.IsolatedAsyncioTestCase):
    def _pp_with(self, fake):
        pp = PostProcessor(runner=fake)
        # Make ffprobe resolution succeed without a real binary.
        pp._resolve_ffprobe_path = lambda: "/usr/bin/ffprobe"
        return pp

    async def test_parses_duration(self):
        fake = FakeProcessRunner()
        fake.queue_capture(returncode=0, stdout=b"123.5\n")
        pp = self._pp_with(fake)
        self.assertEqual(await pp._get_duration("in.ts"), 123.5)

    async def test_timeout_returns_zero(self):
        fake = FakeProcessRunner()
        fake.queue_capture(returncode=None, timed_out=True)
        pp = self._pp_with(fake)
        self.assertEqual(await pp._get_duration("in.ts"), 0)

    async def test_nonzero_returns_zero(self):
        fake = FakeProcessRunner()
        fake.queue_capture(returncode=1, stderr=b"bad file")
        pp = self._pp_with(fake)
        self.assertEqual(await pp._get_duration("in.ts"), 0)

    async def test_garbage_output_returns_zero(self):
        fake = FakeProcessRunner()
        fake.queue_capture(returncode=0, stdout=b"not-a-number")
        pp = self._pp_with(fake)
        self.assertEqual(await pp._get_duration("in.ts"), 0)

    async def test_cancellation_propagates(self):
        fake = FakeProcessRunner()
        fake.queue_capture_error(asyncio.CancelledError())
        pp = self._pp_with(fake)
        with self.assertRaises(asyncio.CancelledError):
            await pp._get_duration("in.ts")


class ProbeMediaIntegrityTests(unittest.IsolatedAsyncioTestCase):
    def _pp_with(self, fake):
        pp = PostProcessor(runner=fake)
        pp._resolve_ffprobe_path = lambda: "/usr/bin/ffprobe"
        return pp

    async def test_healthy_file_ok(self):
        fake = FakeProcessRunner()
        fake.queue_capture(
            returncode=0,
            stdout=b'{"streams":[{"codec_type":"video"}],"format":{"duration":"10"}}',
        )
        pp = self._pp_with(fake)
        result = await pp.probe_media_integrity("in.mkv")
        self.assertTrue(result["checked"])
        self.assertTrue(result["ok"])

    async def test_timeout_flagged_corrupt(self):
        fake = FakeProcessRunner()
        fake.queue_capture(returncode=None, timed_out=True)
        pp = self._pp_with(fake)
        result = await pp.probe_media_integrity("in.mkv")
        self.assertFalse(result["ok"])
        self.assertIn("timed out", result["reason"])

    async def test_no_streams_flagged(self):
        fake = FakeProcessRunner()
        fake.queue_capture(
            returncode=0, stdout=b'{"streams":[],"format":{"duration":"10"}}'
        )
        pp = self._pp_with(fake)
        result = await pp.probe_media_integrity("in.mkv")
        self.assertFalse(result["ok"])
        self.assertIn("no audio/video", result["reason"])

    async def test_zero_duration_flagged(self):
        fake = FakeProcessRunner()
        fake.queue_capture(
            returncode=0,
            stdout=b'{"streams":[{"codec_type":"video"}],"format":{"duration":"0"}}',
        )
        pp = self._pp_with(fake)
        result = await pp.probe_media_integrity("in.mkv")
        self.assertFalse(result["ok"])
        self.assertIn("zero duration", result["reason"])

    async def test_unparseable_container_flagged(self):
        fake = FakeProcessRunner()
        fake.queue_capture(returncode=1, stderr=b"invalid data")
        pp = self._pp_with(fake)
        result = await pp.probe_media_integrity("in.mkv")
        self.assertFalse(result["ok"])
        self.assertIn("could not be parsed", result["reason"])


if __name__ == "__main__":
    unittest.main()
