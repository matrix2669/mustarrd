"""Tests for the Comskip settings editor API fields.

Covers the validation contract from docs/design/comskip-settings-editor.md:
- detect_method bounded 0..255 in SettingsUpdate
- thread_count clamped (not rejected) to 1..16 on save
- min<=max enforced for commercialbreak and commercial_size pairs on the
  FINAL stored state, so two separate PUT requests cannot create an
  inverted range
- custom INI mode is explicit, requires a readable absolute file path, expands
  user-home paths before saving, and blank paths normalize to NULL
- GET /settings returns the new fields with their defaults
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from database import Base
from models import AppSettings
from api.settings import SettingsUpdate, update_settings


class ComskipFieldValidationTests(unittest.TestCase):
    def test_detect_method_bounds(self):
        self.assertEqual(SettingsUpdate(comskip_detect_method=0).comskip_detect_method, 0)
        self.assertEqual(SettingsUpdate(comskip_detect_method=255).comskip_detect_method, 255)
        with self.assertRaises(ValidationError):
            SettingsUpdate(comskip_detect_method=-1)
        with self.assertRaises(ValidationError):
            SettingsUpdate(comskip_detect_method=256)

    def test_timing_fields_reject_negative(self):
        for field in (
            "comskip_max_commercialbreak",
            "comskip_min_commercialbreak",
            "comskip_max_commercial_size",
            "comskip_min_commercial_size",
            "comskip_always_keep_first_seconds",
            "comskip_always_keep_last_seconds",
            "comskip_remove_before",
            "comskip_remove_after",
        ):
            with self.assertRaises(ValidationError, msg=field):
                SettingsUpdate(**{field: -1})
            self.assertEqual(getattr(SettingsUpdate(**{field: 0}), field), 0)


class ComskipTunablesUpdateTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.session_factory = async_sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def _seed(self, **values):
        async with self.session_factory() as session:
            settings = AppSettings(**values)
            session.add(settings)
            await session.commit()

    async def _update(self, **update):
        async with self.session_factory() as session:
            return await update_settings(
                update_data=SettingsUpdate(**update),
                _admin=None,
                session=session,
            )

    async def test_defaults_returned_after_any_save(self):
        await self._seed()
        result = await self._update(comskip_enabled=True)
        self.assertEqual(result["comskip_detect_method"], 107)
        self.assertEqual(result["comskip_max_commercialbreak"], 600)
        self.assertEqual(result["comskip_min_commercialbreak"], 25)
        self.assertEqual(result["comskip_max_commercial_size"], 125)
        self.assertEqual(result["comskip_min_commercial_size"], 4)
        self.assertEqual(result["comskip_always_keep_first_seconds"], 0)
        self.assertEqual(result["comskip_always_keep_last_seconds"], 60)
        self.assertEqual(result["comskip_remove_before"], 0)
        self.assertEqual(result["comskip_remove_after"], 0)
        self.assertTrue(result["comskip_connect_blocks_with_logo"])
        self.assertFalse(result["comskip_dynamic_ticker_tape"])
        self.assertEqual(result["comskip_thread_count"], 1)
        self.assertFalse(result["comskip_use_custom_ini"])
        self.assertIsNone(result["comskip_custom_ini_path"])

    async def test_thread_count_clamped_low_and_high(self):
        await self._seed()
        result = await self._update(comskip_thread_count=0)
        self.assertEqual(result["comskip_thread_count"], 1)
        result = await self._update(comskip_thread_count=99)
        self.assertEqual(result["comskip_thread_count"], 16)
        result = await self._update(comskip_thread_count=8)
        self.assertEqual(result["comskip_thread_count"], 8)

    async def test_inverted_commercialbreak_pair_rejected(self):
        await self._seed()
        with self.assertRaises(HTTPException) as ctx:
            await self._update(
                comskip_min_commercialbreak=700, comskip_max_commercialbreak=600
            )
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_inverted_commercial_size_pair_rejected(self):
        await self._seed()
        with self.assertRaises(HTTPException) as ctx:
            await self._update(
                comskip_min_commercial_size=200, comskip_max_commercial_size=125
            )
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_inverted_pair_rejected_across_two_requests(self):
        """Raising only the min in a second request must hit final-state validation."""
        await self._seed(comskip_max_commercialbreak=600)
        with self.assertRaises(HTTPException) as ctx:
            await self._update(comskip_min_commercialbreak=601)
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_inverted_pair_not_persisted(self):
        await self._seed(comskip_min_commercialbreak=25)
        with self.assertRaises(HTTPException):
            await self._update(comskip_min_commercialbreak=9999)
        result = await self._update(comskip_enabled=False)
        self.assertEqual(result["comskip_min_commercialbreak"], 25)

    async def test_equal_pair_accepted(self):
        await self._seed()
        result = await self._update(
            comskip_min_commercialbreak=100, comskip_max_commercialbreak=100
        )
        self.assertEqual(result["comskip_min_commercialbreak"], 100)
        self.assertEqual(result["comskip_max_commercialbreak"], 100)

    async def test_custom_ini_path_set_and_cleared(self):
        await self._seed()
        result = await self._update(comskip_custom_ini_path="/tmp/my.ini")
        self.assertEqual(result["comskip_custom_ini_path"], "/tmp/my.ini")
        result = await self._update(comskip_custom_ini_path=None)
        self.assertIsNone(result["comskip_custom_ini_path"])

    async def test_custom_ini_mode_requires_a_path(self):
        await self._seed()
        with self.assertRaises(HTTPException) as ctx:
            await self._update(comskip_use_custom_ini=True)
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_custom_ini_mode_and_path_persist(self):
        await self._seed()
        with tempfile.NamedTemporaryFile(suffix=".ini") as custom_ini:
            custom_ini.write(b"output_edl=1\n")
            custom_ini.flush()
            result = await self._update(
                comskip_use_custom_ini=True,
                comskip_custom_ini_path=custom_ini.name,
            )
            self.assertTrue(result["comskip_use_custom_ini"])
            self.assertEqual(result["comskip_custom_ini_path"], custom_ini.name)

    async def test_custom_ini_mode_expands_home_path_before_saving(self):
        await self._seed()
        with tempfile.NamedTemporaryFile(suffix=".ini") as custom_ini:
            custom_ini.write(b"output_edl=1\n")
            custom_ini.flush()
            with patch("api.settings.os.path.expanduser", return_value=custom_ini.name):
                result = await self._update(
                    comskip_use_custom_ini=True,
                    comskip_custom_ini_path="~/custom-comskip.ini",
                )
            self.assertEqual(
                result["comskip_custom_ini_path"],
                str(Path(custom_ini.name).absolute()),
            )

    async def test_custom_ini_mode_rejects_relative_path(self):
        await self._seed()
        with self.assertRaises(HTTPException) as ctx:
            await self._update(
                comskip_use_custom_ini=True,
                comskip_custom_ini_path="custom.ini",
            )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("absolute path", ctx.exception.detail)

    async def test_custom_ini_mode_rejects_missing_file(self):
        await self._seed()
        with tempfile.TemporaryDirectory() as temp_dir:
            missing_path = str(Path(temp_dir) / "missing.ini")
            with self.assertRaises(HTTPException) as ctx:
                await self._update(
                    comskip_use_custom_ini=True,
                    comskip_custom_ini_path=missing_path,
                )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("not found", ctx.exception.detail)

    async def test_custom_ini_mode_rejects_directory(self):
        await self._seed()
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(HTTPException) as ctx:
                await self._update(
                    comskip_use_custom_ini=True,
                    comskip_custom_ini_path=temp_dir,
                )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("not a regular file", ctx.exception.detail)

    async def test_custom_ini_mode_rejects_unreadable_file(self):
        await self._seed()
        with tempfile.NamedTemporaryFile(suffix=".ini") as custom_ini:
            with patch("builtins.open", side_effect=PermissionError("denied")):
                with self.assertRaises(HTTPException) as ctx:
                    await self._update(
                        comskip_use_custom_ini=True,
                        comskip_custom_ini_path=custom_ini.name,
                    )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("not readable", ctx.exception.detail)

    async def test_blank_custom_ini_path_normalizes_to_null(self):
        await self._seed(comskip_custom_ini_path="/tmp/my.ini")
        result = await self._update(comskip_custom_ini_path="   ")
        self.assertIsNone(result["comskip_custom_ini_path"])

    async def test_tunables_survive_unrelated_save(self):
        await self._seed(comskip_detect_method=43, comskip_thread_count=4)
        result = await self._update(comskip_path="/usr/bin/comskip")
        self.assertEqual(result["comskip_detect_method"], 43)
        self.assertEqual(result["comskip_thread_count"], 4)


if __name__ == "__main__":
    unittest.main()
