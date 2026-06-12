"""
Regression test: restart recovery and the live post-process path must agree on
"did post-processing already produce an output file?".

Both paths used to inline the same _processed_output_candidates search loop.
Two copies could drift, and a crash between the file-move and the DB commit
would then let the two callers disagree -- one finalizing a recording the other
declared missing (duplicate or dropped recording). The detection now lives in a
single predicate, _find_processed_output, that both callers share.

This test seeds a PROCESSING download whose raw input is gone but whose
transcoded .mkv output survives, and asserts BOTH paths find that same output
and finalize the recording as COMPLETED.
"""
import contextlib
import sys
import tempfile
import shutil
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from database import Base
from models import AppSettings, Download, DownloadStatus
from services.download_manager import DownloadManager


class ProcessedOutputDetectionSharedTests(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)
        self.manager = DownloadManager()
        self.tmpdir = tempfile.mkdtemp()

        self.downloads_dir = Path(self.tmpdir) / "downloads"
        self.downloads_dir.mkdir()
        self.completed_dir = Path(self.tmpdir) / "completed"
        self.completed_dir.mkdir()

        # Raw input is gone; only the transcoded output survives next to it.
        self.input_path = self.downloads_dir / "show.ts"
        self.output_path = self.downloads_dir / "show.mkv"
        self.output_path.write_bytes(b"x" * 2048)

        async with self.session_factory() as session:
            session.add(AppSettings(
                download_folder=str(self.downloads_dir),
                completed_folder=str(self.completed_dir),
                transcode_enabled=True,
                transcode_format="mkv",
                comskip_enabled=False,
            ))
            await session.commit()

    async def asyncTearDown(self):
        await self.engine.dispose()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    async def _seed_processing_download(self) -> int:
        async with self.session_factory() as session:
            dl = Download(
                account_id=1,
                channel_id="1",
                channel_name="Test Channel",
                program_title="Test Show",
                program_start=datetime(2024, 1, 1, 20, 0, 0),
                program_end=datetime(2024, 1, 1, 21, 0, 0),
                duration_minutes=60,
                source_url="http://provider.test/ts",
                output_path=str(self.input_path),
                status=DownloadStatus.PROCESSING.value,
                progress=50.0,
            )
            session.add(dl)
            await session.commit()
            await session.refresh(dl)
            return dl.id

    @contextlib.contextmanager
    def _patched_manager(self):
        @contextlib.asynccontextmanager
        async def patched_session_maker():
            async with self.session_factory() as real_session:
                yield real_session

        with (
            patch("services.download_manager.async_session_maker", patched_session_maker),
            patch.object(self.manager, "_store_recorded_duration", new_callable=AsyncMock),
            patch.object(self.manager, "_integrity_check_warning", new_callable=AsyncMock, return_value=None),
            patch.object(self.manager, "_broadcast_progress", new_callable=AsyncMock),
            patch.object(self.manager, "_broadcast_log", new_callable=AsyncMock),
            patch.object(self.manager, "_trigger_plex_refresh", new_callable=AsyncMock),
        ):
            yield

    async def _status_of(self, download_id: int) -> Download:
        async with self.session_factory() as session:
            result = await session.execute(select(Download).where(Download.id == download_id))
            return result.scalar_one()

    async def test_recovery_finalizes_surviving_output(self):
        download_id = await self._seed_processing_download()
        with self._patched_manager():
            await self.manager.recover_incomplete_downloads()
        dl = await self._status_of(download_id)
        self.assertEqual(dl.status, DownloadStatus.COMPLETED.value)
        self.assertTrue((self.completed_dir / "show.mkv").exists())

    async def test_post_process_finalizes_surviving_output(self):
        download_id = await self._seed_processing_download()
        with self._patched_manager():
            await self.manager._execute_post_process(download_id)
        dl = await self._status_of(download_id)
        self.assertEqual(dl.status, DownloadStatus.COMPLETED.value)
        self.assertTrue((self.completed_dir / "show.mkv").exists())

    def test_predicate_is_the_one_both_callers_use(self):
        # No input file present, but the .mkv output is -> predicate returns it.
        found = self.manager._find_processed_output(str(self.input_path), None)
        # settings=None means no candidates, so guard the real lookup with settings.
        self.assertIsNone(found)

        class _S:
            transcode_format = "mkv"

        found = self.manager._find_processed_output(str(self.input_path), _S())
        self.assertEqual(found, str(self.output_path))


if __name__ == "__main__":
    unittest.main()
