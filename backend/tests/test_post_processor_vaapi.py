import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE_PATH = Path(__file__).resolve().parents[1] / "services" / "post_processor.py"
SPEC = importlib.util.spec_from_file_location("post_processor_under_test", MODULE_PATH)
POST_PROCESSOR_MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(POST_PROCESSOR_MODULE)

HardwareAccel = POST_PROCESSOR_MODULE.HardwareAccel
PostProcessor = POST_PROCESSOR_MODULE.PostProcessor


class VaapiDriverResolutionTests(unittest.TestCase):
    def setUp(self):
        self.processor = PostProcessor()
        self.processor._resolve_vaapi_driver.cache_clear()

    def tearDown(self):
        self.processor._resolve_vaapi_driver.cache_clear()

    def _make_render_device(self, kernel_driver: str) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root = Path(temp_dir.name)

        device = root / "dev" / "dri" / "renderD128"
        device.parent.mkdir(parents=True, exist_ok=True)

        sysfs_base = root / "sysfs"
        resolved_target = sysfs_base / "render" / "device-node"
        resolved_target.parent.mkdir(parents=True, exist_ok=True)
        resolved_target.write_text("")

        (sysfs_base / "device").mkdir(parents=True, exist_ok=True)
        (sysfs_base / "device" / "vendor").write_text("0x1002")

        driver_target = root / "drivers" / kernel_driver
        driver_target.mkdir(parents=True, exist_ok=True)
        (sysfs_base / "device" / "driver").symlink_to(driver_target)
        device.symlink_to(resolved_target)
        return device

    def test_env_override_wins(self):
        with patch.object(POST_PROCESSOR_MODULE.platform, "system", return_value="Linux"):
            with patch.dict(os.environ, {"LIBVA_DRIVER_NAME": "custom-driver"}, clear=False):
                details = self.processor.get_vaapi_diagnostics()

        self.assertTrue(details["enabled"])
        self.assertEqual(details["driver"], "custom-driver")
        self.assertEqual(details["source"], "env")

    def test_amd_kernel_driver_maps_to_radeonsi(self):
        render_device = self._make_render_device("amdgpu")
        with patch.object(POST_PROCESSOR_MODULE.platform, "system", return_value="Linux"):
            with patch.object(PostProcessor, "VAAPI_RENDER_DEVICE", render_device):
                details = self.processor.get_vaapi_diagnostics()

        self.assertEqual(details["driver"], "radeonsi")
        self.assertEqual(details["source"], "auto-detected")
        self.assertEqual(details["kernel_driver"], "amdgpu")

    def test_intel_kernel_driver_maps_to_ihd(self):
        render_device = self._make_render_device("xe")
        with patch.object(POST_PROCESSOR_MODULE.platform, "system", return_value="Linux"):
            with patch.object(PostProcessor, "VAAPI_RENDER_DEVICE", render_device):
                details = self.processor.get_vaapi_diagnostics()

        self.assertEqual(details["driver"], "iHD")
        self.assertEqual(details["source"], "auto-detected")
        self.assertEqual(details["kernel_driver"], "xe")

    def test_unknown_kernel_driver_leaves_driver_unset(self):
        render_device = self._make_render_device("mysterygpu")
        with patch.object(POST_PROCESSOR_MODULE.platform, "system", return_value="Linux"):
            with patch.object(PostProcessor, "VAAPI_RENDER_DEVICE", render_device):
                details = self.processor.get_vaapi_diagnostics()

        self.assertIsNone(details["driver"])
        self.assertEqual(details["source"], "auto")
        self.assertEqual(details["kernel_driver"], "mysterygpu")

    def test_vaapi_env_uses_detected_driver(self):
        render_device = self._make_render_device("amdgpu")
        with patch.object(POST_PROCESSOR_MODULE.platform, "system", return_value="Linux"):
            with patch.object(PostProcessor, "VAAPI_RENDER_DEVICE", render_device):
                env = self.processor._build_ffmpeg_env(HardwareAccel.VAAPI)

        self.assertEqual(env["LIBVA_DRIVER_NAME"], "radeonsi")
        self.assertIn("LIBVA_DRIVERS_PATH", env)

    def test_vaapi_env_does_not_force_unknown_driver(self):
        render_device = self._make_render_device("mysterygpu")
        with patch.object(POST_PROCESSOR_MODULE.platform, "system", return_value="Linux"):
            with patch.object(PostProcessor, "VAAPI_RENDER_DEVICE", render_device):
                env = self.processor._build_ffmpeg_env(HardwareAccel.VAAPI)

        self.assertNotIn("LIBVA_DRIVER_NAME", env)
        self.assertIn("LIBVA_DRIVERS_PATH", env)

    def test_non_vaapi_env_does_not_modify_driver_override(self):
        with patch.object(POST_PROCESSOR_MODULE.platform, "system", return_value="Linux"):
            with patch.dict(os.environ, {"LIBVA_DRIVER_NAME": "keep-me"}, clear=False):
                env = self.processor._build_ffmpeg_env(HardwareAccel.CPU)

        self.assertEqual(env["LIBVA_DRIVER_NAME"], "keep-me")


if __name__ == "__main__":
    unittest.main()
