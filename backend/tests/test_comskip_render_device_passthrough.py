"""Regression test: remove_commercials must forward the chosen render device.

Settings > Post-Processing lets the user pick which GPU encodes. That choice
reaches ffmpeg as ``render_device``. ``remove_commercials`` delegates to
``transcode`` on the two paths where there is nothing to cut (no EDL segments,
or segments that leave nothing to keep), and both previously dropped the
argument. The encode then silently fell back to the first render node found,
so anyone using commercial skip encoded on whichever GPU was enumerated first
rather than the one they selected.
"""
import asyncio
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

MODULE_PATH = Path(__file__).resolve().parents[1] / "services" / "post_processor.py"
SPEC = importlib.util.spec_from_file_location("post_processor_render_device", MODULE_PATH)
POST_PROCESSOR_MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(POST_PROCESSOR_MODULE)

HardwareAccel = POST_PROCESSOR_MODULE.HardwareAccel
OutputFormat = POST_PROCESSOR_MODULE.OutputFormat
PostProcessor = POST_PROCESSOR_MODULE.PostProcessor

RENDER_DEVICE = "/dev/dri/renderD129"


class RemoveCommercialsRenderDeviceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.processor = PostProcessor()
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root = Path(temp_dir.name)

        self.input_path = root / "recording.ts"
        self.input_path.write_bytes(b"")
        self.edl_path = root / "recording.edl"
        self.output_path = root / "recording.mkv"

    async def _call_with_edl(self, edl_text: str, duration: float) -> AsyncMock:
        """Run remove_commercials with a stubbed transcode and return the stub."""
        self.edl_path.write_text(edl_text, encoding="utf-8")
        transcode = AsyncMock(return_value=str(self.output_path))
        with patch.object(self.processor, "transcode", transcode), \
                patch.object(
                    type(self.processor),
                    "ffmpeg_available",
                    property(lambda _self: True),
                ), \
                patch.object(self.processor, "_cleanup_comskip_outputs"), \
                patch.object(
                    self.processor, "_get_duration", AsyncMock(return_value=duration)
                ):
            await self.processor.remove_commercials(
                str(self.input_path),
                str(self.edl_path),
                OutputFormat.MKV,
                HardwareAccel.VAAPI,
                render_device=RENDER_DEVICE,
            )
        return transcode

    async def test_render_device_forwarded_when_edl_has_no_segments(self):
        """An EDL with nothing to cut still encodes on the selected GPU."""
        transcode = await self._call_with_edl("", duration=1800.0)

        transcode.assert_awaited_once()
        self.assertEqual(
            transcode.await_args.kwargs.get("render_device"), RENDER_DEVICE
        )

    async def test_render_device_forwarded_when_nothing_is_kept(self):
        """An EDL covering the whole recording still encodes on the selected GPU."""
        transcode = await self._call_with_edl("0.00\t60.00\t0\n", duration=60.0)

        transcode.assert_awaited_once()
        self.assertEqual(
            transcode.await_args.kwargs.get("render_device"), RENDER_DEVICE
        )


if __name__ == "__main__":
    unittest.main()
