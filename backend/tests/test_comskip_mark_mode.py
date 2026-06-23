"""
Regression tests for Commercial Skip Mark mode (issue #397).

Commercial Skip becomes three-way: Off / Mark / Cut.

- `comskip_enabled` keeps its meaning: "Comskip runs."
- New `comskip_cut` flag (default True = Cut) decides whether the detected
  commercials are physically removed (Cut) or merely marked (Mark).

Mark mode does NOT force a re-encode; Cut still does. See
docs/adr/0001-commercial-skip-mark-mode.md.
"""
import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import importlib.util
import os
import tempfile

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from database import Base
from models import AppSettings
from api.settings import SettingsUpdate, update_settings

_PP_PATH = BACKEND_ROOT / "services" / "post_processor.py"
_PP_SPEC = importlib.util.spec_from_file_location("post_processor_mark_test", _PP_PATH)
_PP_MODULE = importlib.util.module_from_spec(_PP_SPEC)
assert _PP_SPEC and _PP_SPEC.loader
_PP_SPEC.loader.exec_module(_PP_MODULE)
PostProcessor = _PP_MODULE.PostProcessor


class ComskipCutFieldTests(unittest.IsolatedAsyncioTestCase):
    """Slice 1: the comskip_cut flag exists, defaults to Cut, and persists."""

    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.session_factory = async_sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def _apply(self, initial: dict, update: dict) -> dict:
        async with self.session_factory() as session:
            settings = AppSettings(**initial)
            session.add(settings)
            await session.commit()

        async with self.session_factory() as session:
            return await update_settings(
                update_data=SettingsUpdate(**update),
                _admin=None,
                session=session,
            )

    async def test_comskip_cut_defaults_to_cut(self):
        """A row created without comskip_cut comes up as True (Cut).

        Existing comskip_enabled installs must default to Cut so behaviour is
        byte-identical after the upgrade.
        """
        async with self.session_factory() as session:
            settings = AppSettings(comskip_enabled=True)
            session.add(settings)
            await session.commit()
            await session.refresh(settings)
            self.assertTrue(settings.comskip_cut,
                "comskip_cut must default to True (Cut) for byte-identical upgrades")

    async def test_comskip_cut_persists_and_is_exposed(self):
        """Setting comskip_cut=False (Mark) persists and appears in the settings dict."""
        result = await self._apply(
            initial={"comskip_enabled": True},
            update={"comskip_cut": False},
        )
        self.assertIn("comskip_cut", result, "comskip_cut must be exposed via the settings API")
        self.assertFalse(result["comskip_cut"], "comskip_cut=False (Mark) must persist")


class MarkModeConstraintTests(unittest.IsolatedAsyncioTestCase):
    """Slice 2: 'comskip forces re-encode' narrows to Cut mode only.

    Cut (comskip_enabled + comskip_cut) still forces transcode_enabled=True.
    Mark (comskip_enabled + not comskip_cut) must NOT force it: Mark honours
    the format picker, including Keep .ts.
    """

    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.session_factory = async_sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def _apply(self, initial: dict, update: dict) -> dict:
        async with self.session_factory() as session:
            settings = AppSettings(**initial)
            session.add(settings)
            await session.commit()

        async with self.session_factory() as session:
            return await update_settings(
                update_data=SettingsUpdate(**update),
                _admin=None,
                session=session,
            )

    async def test_cut_mode_still_forces_transcode(self):
        """Cut mode (comskip_cut=True) keeps forcing transcode_enabled=True."""
        result = await self._apply(
            initial={"comskip_enabled": False, "transcode_enabled": False, "comskip_cut": True},
            update={"comskip_enabled": True},
        )
        self.assertTrue(result["comskip_enabled"])
        self.assertTrue(result["comskip_cut"])
        self.assertTrue(result["transcode_enabled"],
            "Cut mode must still force transcode_enabled=True")

    async def test_mark_mode_does_not_force_transcode(self):
        """Mark mode (comskip_cut=False) must NOT force transcode_enabled.

        Mark + Keep .ts is a valid combination: transcode_enabled=False stays.
        """
        result = await self._apply(
            initial={"comskip_enabled": False, "transcode_enabled": False},
            update={"comskip_enabled": True, "comskip_cut": False},
        )
        self.assertTrue(result["comskip_enabled"])
        self.assertFalse(result["comskip_cut"])
        self.assertFalse(result["transcode_enabled"],
            "Mark mode must not force transcode_enabled; it honours the format picker")

    async def test_switching_cut_to_mark_releases_forced_transcode(self):
        """Turning an existing Cut install into Mark stops forcing transcode."""
        result = await self._apply(
            initial={"comskip_enabled": True, "comskip_cut": True, "transcode_enabled": True},
            update={"comskip_cut": False, "transcode_enabled": False},
        )
        self.assertFalse(result["comskip_cut"])
        self.assertFalse(result["transcode_enabled"],
            "Mark mode must let the user turn transcode off (Keep .ts)")


class FfmetadataChaptersTests(unittest.TestCase):
    """Slice 3: derive ffmetadata chapters from parsed EDL segments.

    Commercial spans are labeled "Commercial"; the content spans between them
    are chaptered too, so a Plex client can jump break-to-break by chapter.
    """

    def setUp(self):
        self.processor = PostProcessor()

    def test_no_segments_yields_no_chapters(self):
        """No commercials detected → no chapter metadata (falsy)."""
        out = self.processor._edl_to_ffmetadata_chapters([], 1800.0)
        self.assertFalse(out, "No commercial segments must produce no chapters")

    def test_commercial_span_labeled_and_timed(self):
        """A commercial span becomes a 'Commercial' chapter with millisecond bounds."""
        segments = [(60.0, 120.0, 0)]
        out = self.processor._edl_to_ffmetadata_chapters(segments, 180.0)

        self.assertIn(";FFMETADATA1", out, "must start with the ffmetadata header")
        self.assertIn("title=Commercial", out, "commercial span must be labeled Commercial")
        # Default ffmetadata chapter timebase is 1/1000 (milliseconds).
        self.assertIn("START=60000", out, "commercial chapter must start at 60s = 60000ms")
        self.assertIn("END=120000", out, "commercial chapter must end at 120s = 120000ms")

    def test_content_gaps_are_chaptered(self):
        """Content spans around the commercial are chaptered too.

        For commercial [60,120] in a 180s file there are three chapters:
        content [0,60], commercial [60,120], content [120,180].
        """
        segments = [(60.0, 120.0, 0)]
        out = self.processor._edl_to_ffmetadata_chapters(segments, 180.0)

        self.assertEqual(out.count("[CHAPTER]"), 3,
            "expected content + commercial + content = 3 chapters")
        self.assertIn("START=120000", out, "trailing content chapter must start at 120000ms")
        self.assertIn("END=180000", out, "trailing content chapter must end at duration (180000ms)")


class EmbedChaptersGuardTests(unittest.IsolatedAsyncioTestCase):
    """Slice 5 (unit): chapters can't go in MPEG-TS, so Keep .ts gets no chapters."""

    def setUp(self):
        self.processor = PostProcessor()
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.tmp)

    async def test_ts_container_gets_no_chapters(self):
        """embed_chapters is a no-op for a .ts file (returns it untouched)."""
        ts = Path(self.tmp) / "Show.ts"
        ts.write_bytes(b"\x47" * 188)
        edl = Path(self.tmp) / "Show.edl"
        edl.write_text("60.00 120.00 0\n")

        result = await self.processor.embed_chapters(str(ts), str(edl))

        self.assertEqual(result, str(ts), "Keep .ts must not be rewritten for chapters")
        self.assertEqual(ts.read_bytes(), b"\x47" * 188, "the .ts must be left byte-identical")


class EdlSidecarTests(unittest.TestCase):
    """Slice 4: Mark mode keeps the EDL as a sidecar named after the final video.

    `Show - S01E04.mkv` → `Show - S01E04.edl`, in the same folder. No sidecar
    when Comskip found nothing.
    """

    def setUp(self):
        self.processor = PostProcessor()
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.tmp)

    def _path(self, name: str) -> str:
        return str(Path(self.tmp) / name)

    def _write(self, name: str, content: str) -> str:
        p = Path(self.tmp) / name
        p.write_text(content)
        return str(p)

    def test_sidecar_matches_video_stem(self):
        """Sidecar is <video stem>.edl beside the video and carries the segments."""
        video = self._path("Show - S01E04.mkv")
        edl = self._write("Show - S01E04.edl", "60.00 120.00 0\n")

        sidecar = self.processor._write_edl_sidecar(video, edl)

        self.assertEqual(sidecar, self._path("Show - S01E04.edl"))
        self.assertTrue(os.path.exists(sidecar), "sidecar must exist beside the video")
        self.assertIn("60.00", Path(sidecar).read_text())

    def test_no_commercials_no_sidecar(self):
        """An EDL with no commercial entries yields no sidecar."""
        video = self._path("Show - S01E04.mkv")
        edl = self._write("Show - S01E04.edl", "")

        sidecar = self.processor._write_edl_sidecar(video, edl)

        self.assertIsNone(sidecar, "no commercials → no sidecar")
        self.assertFalse(os.path.exists(self._path("Show - S01E04.edl")) and
                         Path(self._path("Show - S01E04.edl")).read_text().strip() != "",
                         "must not leave a non-empty stray sidecar")

    def test_probe_named_edl_renamed_to_video_stem(self):
        """When Comskip retried on a probe file, the EDL stem differs; rename it.

        detection EDL = 'Show_comskip_input.edl', final video = 'Show.mkv'
        → sidecar must be 'Show.edl'.
        """
        video = self._path("Show.mkv")
        edl = self._write("Show_comskip_input.edl", "60.00 120.00 0\n")

        sidecar = self.processor._write_edl_sidecar(video, edl)

        self.assertEqual(sidecar, self._path("Show.edl"))
        self.assertTrue(os.path.exists(sidecar))


if __name__ == "__main__":
    unittest.main()
