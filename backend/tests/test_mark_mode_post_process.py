"""
Acceptance test for Commercial Skip Mark mode orchestration (issue #397).

Drives DownloadManager._post_process with a faked post_processor and asserts the
Mark-mode contract:

  - the cut is NOT applied (remove_commercials is never called),
  - chapters are embedded on the container pass (embed_chapters is called),
  - the .edl sidecar is kept, named after the final video.

See docs/adr/0001-commercial-skip-mark-mode.md and 0002-...chapters.md.
"""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from models import AppSettings
from services.download_manager import DownloadManager
from services import post_processor as pp_module


class MarkModePostProcessTests(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.manager = DownloadManager()
        self.download_dir = tempfile.mkdtemp()
        self.completed_dir = tempfile.mkdtemp()

    async def asyncTearDown(self):
        shutil.rmtree(self.download_dir, ignore_errors=True)
        shutil.rmtree(self.completed_dir, ignore_errors=True)

    def _settings(self, **overrides) -> AppSettings:
        base = dict(
            comskip_enabled=True,
            comskip_cut=False,  # Mark
            transcode_enabled=True,
            transcode_format="mkv",
            hw_accel="cpu",
            remux_only=False,
            delete_original_after_transcode=False,
            min_free_space_gb=0,
            download_folder=self.download_dir,
            completed_folder=self.completed_dir,
        )
        base.update(overrides)
        return AppSettings(**base)

    async def _run(self, settings: AppSettings):
        ts_path = os.path.join(self.download_dir, "Show.ts")
        Path(ts_path).write_bytes(b"\x47" * 188)
        edl_path = os.path.join(self.download_dir, "Show.edl")

        async def fake_detect(input_path, ini_path=None, **kwargs):
            Path(edl_path).write_text("60.00 120.00 0\n")
            return edl_path

        async def fake_transcode(input_path, output_format, **kwargs):
            out = os.path.join(self.download_dir, "Show.mkv")
            Path(out).write_bytes(b"\x00" * 1024)
            return out

        remove_commercials = AsyncMock()
        embed_chapters = AsyncMock(side_effect=lambda video, edl, **k: video)

        with patch.object(pp_module, "post_processor") as pp:
            pp.comskip_available = True
            pp.ffmpeg_available = True
            pp.comskip_path = None
            pp.detect_commercials = AsyncMock(side_effect=fake_detect)
            pp.transcode = AsyncMock(side_effect=fake_transcode)
            pp.remove_commercials = remove_commercials
            pp.embed_chapters = embed_chapters
            # _write_edl_sidecar is a pure file op; delegate to the real one.
            pp._write_edl_sidecar = pp_module.PostProcessor._write_edl_sidecar.__get__(pp)
            pp.resolve_hw_accel = MagicMock(return_value=(pp_module.HardwareAccel.CPU, None))
            pp.get_ffmpeg_path = MagicMock(return_value=None)
            pp.set_comskip_path = MagicMock()

            with patch("services.download_manager.get_free_space_shortfall",
                       AsyncMock(return_value=None)), \
                 patch("services.comskip_ini.resolve_comskip_ini",
                       MagicMock(return_value=(None, False))), \
                 patch.object(self.manager, "_update_processing", AsyncMock()), \
                 patch.object(self.manager, "_broadcast_log", AsyncMock()):
                final_path, warnings = await self.manager._post_process(
                    ts_path, download_id=1, session=MagicMock(), settings=settings
                )

        return final_path, warnings, remove_commercials, embed_chapters

    async def test_mark_mkv_does_not_cut_and_keeps_sidecar(self):
        final_path, warnings, remove_commercials, embed_chapters = await self._run(self._settings())

        remove_commercials.assert_not_called()
        self.assertTrue(embed_chapters.called, "Mark + MKV must embed commercial chapters")
        self.assertTrue(final_path.endswith("Show.mkv"), "final output is the unaltered MKV")
        sidecar = os.path.join(self.download_dir, "Show.edl")
        self.assertTrue(os.path.exists(sidecar), "the .edl sidecar must be kept beside the video")
        self.assertEqual(warnings, [])


if __name__ == "__main__":
    unittest.main()
