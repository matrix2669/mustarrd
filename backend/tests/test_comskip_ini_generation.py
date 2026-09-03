"""Tests for generated and custom Comskip INI resolution."""
import asyncio
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from models import AppSettings
from services.comskip_ini import (
    ComskipIniError,
    generate_comskip_ini,
    render_comskip_ini,
    resolve_comskip_ini,
    resolved_comskip_ini,
    tunable_overrides,
)


class RenderComskipIniTests(unittest.TestCase):
    def test_replaces_existing_key_and_drops_inline_comment(self):
        base = "detect_method=255\t\t;1=black frame, 2=logo\noutput_edl=1\n"
        result = render_comskip_ini(base, {"detect_method": 107})
        self.assertIn("detect_method=107", result.splitlines())
        self.assertNotIn("255", result)

    def test_preserves_unrelated_lines(self):
        base = "output_edl=1\nmax_volume=500\t; comment\n"
        result = render_comskip_ini(base, {"detect_method": 107})
        lines = result.splitlines()
        self.assertIn("output_edl=1", lines)
        self.assertIn("max_volume=500\t; comment", lines)

    def test_appends_missing_keys(self):
        base = "output_edl=1\n"
        result = render_comskip_ini(base, {"thread_count": 4, "remove_after": 2})
        lines = result.splitlines()
        self.assertIn("thread_count=4", lines)
        self.assertIn("remove_after=2", lines)
        self.assertIn("output_edl=1", lines)

    def test_commented_out_key_is_not_treated_as_assignment(self):
        base = "; detect_method=99 old note\noutput_edl=1\n"
        result = render_comskip_ini(base, {"detect_method": 107})
        lines = result.splitlines()
        self.assertIn("; detect_method=99 old note", lines)
        self.assertIn("detect_method=107", lines)

    def test_tunable_overrides_reads_model_defaults(self):
        overrides = tunable_overrides(AppSettings(
            comskip_detect_method=107,
            comskip_max_commercialbreak=600,
            comskip_min_commercialbreak=25,
            comskip_max_commercial_size=125,
            comskip_min_commercial_size=4,
            comskip_always_keep_first_seconds=0,
            comskip_always_keep_last_seconds=60,
            comskip_remove_before=0,
            comskip_remove_after=0,
            comskip_connect_blocks_with_logo=True,
            comskip_thread_count=1,
        ))
        self.assertEqual(overrides, {
            "detect_method": 107,
            "max_commercialbreak": 600,
            "min_commercialbreak": 25,
            "max_commercial_size": 125,
            "min_commercial_size": 4,
            "always_keep_first_seconds": 0,
            "always_keep_last_seconds": 60,
            "remove_before": 0,
            "remove_after": 0,
            "connect_blocks_with_logo": 1,
            "thread_count": 1,
        })

    def test_unset_tunables_are_skipped(self):
        settings = AppSettings()
        settings.comskip_detect_method = None
        settings.comskip_thread_count = 8
        overrides = tunable_overrides(settings)
        self.assertNotIn("detect_method", overrides)
        self.assertEqual(overrides["thread_count"], 8)


class GenerateAndResolveTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.config_dir = Path(self._tmp.name)
        (self.config_dir / "comskip.ini").write_text(
            "detect_method=255\nconnect_blocks_with_logo=1\noutput_edl=1\n",
            encoding="utf-8",
        )
        self.settings = AppSettings(
            comskip_detect_method=107,
            comskip_connect_blocks_with_logo=True,
            comskip_thread_count=2,
        )

    def tearDown(self):
        self._tmp.cleanup()

    def _patch_config(self):
        return patch("services.comskip_ini.ensure_config_files", return_value=self.config_dir)

    def test_generate_writes_unique_temporary_ini_in_config_dir(self):
        with self._patch_config():
            path = generate_comskip_ini(self.settings)
            second_path = generate_comskip_ini(self.settings)
        try:
            self.assertNotEqual(path, second_path)
            self.assertEqual(Path(path).parent, self.config_dir)
            self.assertEqual(Path(second_path).parent, self.config_dir)
            self.assertTrue(Path(path).name.startswith(".mustarrd-comskip-"))
            content = Path(path).read_text(encoding="utf-8")
            self.assertIn("detect_method=107", content.splitlines())
            self.assertIn("thread_count=2", content.splitlines())
            self.assertIn("output_edl=1", content.splitlines())
        finally:
            Path(path).unlink(missing_ok=True)
            Path(second_path).unlink(missing_ok=True)

    def test_runtime_overrides_take_precedence(self):
        with self._patch_config():
            path = generate_comskip_ini(self.settings, {"ticker_tape": 120})
        try:
            self.assertIn("ticker_tape=120", Path(path).read_text().splitlines())
        finally:
            Path(path).unlink(missing_ok=True)

    def test_enabled_logo_default_matches_bundled_base(self):
        with self._patch_config():
            path = generate_comskip_ini(self.settings)
        try:
            self.assertIn("connect_blocks_with_logo=1", Path(path).read_text().splitlines())
        finally:
            Path(path).unlink(missing_ok=True)

    def test_user_can_disable_logo_block_connection(self):
        self.settings.comskip_connect_blocks_with_logo = False
        with self._patch_config():
            path = generate_comskip_ini(self.settings)
        try:
            self.assertIn("connect_blocks_with_logo=0", Path(path).read_text().splitlines())
        finally:
            Path(path).unlink(missing_ok=True)

    def test_generate_falls_back_to_minimal_base_with_edl(self):
        (self.config_dir / "comskip.ini").unlink()
        with self._patch_config(), patch(
            "services.comskip_ini._resolve_bundled_comskip_ini", return_value=None
        ):
            path = generate_comskip_ini(self.settings)
        try:
            content = Path(path).read_text(encoding="utf-8")
            self.assertIn("output_edl=1", content.splitlines())
            self.assertIn("detect_method=107", content.splitlines())
        finally:
            Path(path).unlink(missing_ok=True)

    def test_resolve_prefers_valid_custom_ini_and_skips_generation(self):
        custom_path = self.config_dir / "custom.ini"
        custom_path.write_text("output_edl=1\n", encoding="utf-8")
        self.settings.comskip_use_custom_ini = True
        self.settings.comskip_custom_ini_path = str(custom_path)
        with patch("services.comskip_ini.generate_comskip_ini") as mock_generate:
            result, is_temporary = resolve_comskip_ini(self.settings)
        self.assertEqual(result, str(custom_path.absolute()))
        self.assertFalse(is_temporary)
        mock_generate.assert_not_called()

    def test_resolve_custom_mode_fails_closed_when_file_moves(self):
        self.settings.comskip_use_custom_ini = True
        self.settings.comskip_custom_ini_path = str(self.config_dir / "missing.ini")
        with patch("services.comskip_ini.generate_comskip_ini") as mock_generate:
            with self.assertRaisesRegex(ComskipIniError, "not found"):
                resolve_comskip_ini(self.settings)
        mock_generate.assert_not_called()

    def test_resolve_custom_mode_requires_path(self):
        self.settings.comskip_use_custom_ini = True
        self.settings.comskip_custom_ini_path = "   "
        with self.assertRaisesRegex(ComskipIniError, "required"):
            resolve_comskip_ini(self.settings)

    def test_resolve_ignores_saved_custom_path_when_custom_mode_is_off(self):
        self.settings.comskip_use_custom_ini = False
        self.settings.comskip_custom_ini_path = "/custom/comskip.ini"
        with self._patch_config():
            result, is_temporary = resolve_comskip_ini(self.settings)
        try:
            self.assertTrue(Path(result).name.startswith(".mustarrd-comskip-"))
            self.assertTrue(is_temporary)
        finally:
            Path(result).unlink(missing_ok=True)

    def test_resolve_falls_back_to_legacy_path_without_ownership(self):
        self.settings.comskip_custom_ini_path = None
        self.settings.comskip_ini_path = "/legacy/comskip.ini"
        with patch("services.comskip_ini.generate_comskip_ini", return_value=None):
            result, is_temporary = resolve_comskip_ini(self.settings)
        self.assertEqual(result, "/legacy/comskip.ini")
        self.assertFalse(is_temporary)


class ResolvedIniLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addAsyncCleanup(self._cleanup_tempdir)
        self.config_dir = Path(self._tmp.name)
        (self.config_dir / "comskip.ini").write_text(
            "output_edl=1\nconnect_blocks_with_logo=1\n", encoding="utf-8"
        )
        self.settings = AppSettings(comskip_connect_blocks_with_logo=True)

    async def _cleanup_tempdir(self):
        self._tmp.cleanup()

    def _patch_config(self):
        return patch("services.comskip_ini.ensure_config_files", return_value=self.config_dir)

    async def test_generated_ini_removed_after_success(self):
        with self._patch_config():
            async with resolved_comskip_ini(self.settings) as path:
                generated = Path(path)
                self.assertTrue(generated.exists())
        self.assertFalse(generated.exists())

    async def test_generated_ini_removed_after_failure(self):
        generated = None
        with self._patch_config():
            with self.assertRaisesRegex(RuntimeError, "boom"):
                async with resolved_comskip_ini(self.settings) as path:
                    generated = Path(path)
                    raise RuntimeError("boom")
        self.assertIsNotNone(generated)
        self.assertFalse(generated.exists())

    async def test_generated_ini_removed_when_resolution_is_cancelled(self):
        generated = self.config_dir / ".mustarrd-comskip-cancel.ini"
        started = threading.Event()
        release = threading.Event()
        finished = threading.Event()

        def slow_resolve(*_args):
            generated.write_text("output_edl=1\n", encoding="utf-8")
            started.set()
            release.wait(timeout=2)
            finished.set()
            return str(generated), True

        async def use_ini():
            async with resolved_comskip_ini(self.settings):
                self.fail("The context must not be entered after cancellation")

        with patch(
            "services.comskip_ini.resolve_comskip_ini", side_effect=slow_resolve
        ):
            task = asyncio.create_task(use_ini())
            self.assertTrue(await asyncio.to_thread(started.wait, 2))
            task.cancel()
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertTrue(await asyncio.to_thread(finished.wait, 2))

        self.assertFalse(generated.exists())

    async def test_custom_ini_is_never_deleted(self):
        custom = self.config_dir / "custom.ini"
        custom.write_text("output_edl=1\n", encoding="utf-8")
        self.settings.comskip_use_custom_ini = True
        self.settings.comskip_custom_ini_path = str(custom)
        async with resolved_comskip_ini(self.settings) as path:
            self.assertEqual(Path(path), custom)
        self.assertTrue(custom.exists())


if __name__ == "__main__":
    unittest.main()
