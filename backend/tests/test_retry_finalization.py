"""Deferred raw attempts are finalized once, then safely cleaned by ownership."""
import asyncio
import json
import shutil
import subprocess
import tempfile
import unittest
from contextlib import ExitStack
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from database import Base, _apply_lightweight_migrations
from models import AppSettings, Download, DownloadStatus, XtreamAccount
from services import retained_captures
from services.download_manager import DownloadManager
from services.scheduled_manager import ScheduledManager
from tests.test_short_download_retry import recording


class RetryFinalizationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.raw, self.completed = self.root / 'downloads', self.root / 'completed'
        self.raw.mkdir()
        self.completed.mkdir()
        self.engine = create_async_engine('sqlite+aiosqlite:///:memory:')
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.sessions() as session:
            session.add(XtreamAccount(id=1, name='Fixture', server_url='http://example.test', username='u', password='p'))
            session.add(AppSettings(download_folder=str(self.raw), completed_folder=str(self.completed),
                min_free_space_gb=0, mark_short_downloads_failed=True, auto_retry_failed_downloads=True,
                transcode_enabled=True, comskip_enabled=False, write_nfo_files=False,
                delete_original_after_transcode=True))
            self.download = recording(self.raw/'show.ts', duration_minutes=1)
            session.add(self.download)
            await session.commit()
        self.manager, self.scheduler = DownloadManager(), ScheduledManager()
        self.stack = ExitStack()
        self.stack.enter_context(patch('services.download_manager.async_session_maker', self.sessions))
        self.stack.enter_context(patch('services.scheduled_manager.async_session_maker', self.sessions))
        self.stack.enter_context(patch('services.scheduled_manager.download_manager', self.manager))
        self.stack.enter_context(patch.object(self.scheduler, '_get_free_space_gb', AsyncMock(return_value=1000)))
        self.archive = self.stack.enter_context(patch.object(self.scheduler, '_get_archive_days_raw', AsyncMock(return_value=7)))
        self.probe = self.stack.enter_context(patch('services.post_processor.post_processor._get_duration', AsyncMock(return_value=50)))
        self.stack.enter_context(patch.object(self.manager, '_partial_is_playable', AsyncMock(side_effect=lambda p: bool(p and Path(p).is_file() and Path(p).stat().st_size))))
        self.stack.enter_context(patch.object(self.manager, '_integrity_check_warning', AsyncMock(return_value=None)))
        self.stack.enter_context(patch.object(self.manager, '_trigger_plex_refresh', AsyncMock()))
        self.processed = []
        async def process(path, *args, **kwargs):
            self.processed.append(path)
            target = Path(path).with_suffix('.mkv')
            target.write_bytes(Path(path).read_bytes())
            return str(target), []
        self.processor = self.stack.enter_context(patch.object(self.manager, '_post_process', AsyncMock(side_effect=process)))

    async def asyncTearDown(self):
        self.stack.close()
        await self.engine.dispose()
        self.temp.cleanup()

    async def row(self):
        async with self.sessions() as session:
            return await session.get(Download, self.download.id)

    async def settings(self, **changes):
        async with self.sessions() as session:
            row = (await session.execute(select(AppSettings))).scalar_one()
            for key,value in changes.items():
                setattr(row,key,value)
            await session.commit()

    async def age(self):
        async with self.sessions() as session:
            row = await session.get(Download,self.download.id)
            row.last_retry_at = row.completed_at = datetime.utcnow()-timedelta(minutes=30)
            await session.commit()

    async def capture(self, seconds=50, *, fail=False):
        row = await self.row()
        path = Path(row.output_path)
        self.probe.return_value = seconds
        async def transfer(*args, **kwargs):
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(f'raw-attempt-{row.retry_count}-{seconds}'.encode())
            if fail:
                raise RuntimeError('Provider failed')
            return path.stat().st_size
        with patch.object(self.manager,'_download_catchup_stream',AsyncMock(side_effect=transfer)):
            if fail:
                with patch.object(self.manager,'_partial_is_playable',AsyncMock(return_value=False)):
                    await self.manager._execute_download(row.id)
            else:
                await self.manager._execute_download(row.id)
        return path

    async def retry(self):
        await self.age()
        await self.scheduler._auto_retry_failed_downloads()
        self.assertEqual(self.manager._queue.get_nowait(),self.download.id)

    async def finish(self):
        self.assertEqual(self.manager._post_queue.get_nowait(),self.download.id)
        await self.manager._execute_post_process(self.download.id)

    async def test_four_short_captures_process_only_last_and_remove_superseded_files(self):
        paths=[]
        for attempt in range(4):
            paths.append(await self.capture())
            row=await self.row()
            if attempt < 3:
                self.assertTrue(row.processing_deferred)
                self.assertEqual(row.status,'failed')
                self.assertEqual(self.processed,[])
                self.assertTrue(self.manager._post_queue.empty())
                await self.retry()
        await self.finish()
        final=await self.row()
        self.assertEqual(final.status,'failed')
        self.assertTrue(final.short_file_failed)
        self.assertTrue(final.retry_finalized)
        self.assertFalse(final.processing_deferred)
        self.assertEqual(final.retry_count,3)
        self.assertEqual(len(self.processed),1)
        self.assertEqual(final.raw_duration_seconds,50)
        self.assertIsNone(final.retained_captures_json)
        self.assertEqual([p for p in self.root.rglob('*') if p.is_file()],[Path(final.output_path)])
        await self.age()
        await self.scheduler._auto_retry_failed_downloads()
        self.assertTrue(self.manager._queue.empty())
        self.assertTrue(self.manager._post_queue.empty())

    async def test_complete_retry_processes_once_and_keeps_only_successful_output(self):
        old=await self.capture()
        await self.retry()
        await self.capture(60)
        await self.finish()
        final=await self.row()
        self.assertEqual(final.status,'completed')
        self.assertEqual(len(self.processed),1)
        self.assertFalse(old.exists())
        self.assertIsNone(final.retained_captures_json)
        self.assertEqual(len(list(self.root.rglob('*.mkv'))),1)

    async def test_failed_last_transfer_finalizes_previous_playable_attempt(self):
        old=None
        for attempt in range(3):
            old=await self.capture()
            await self.retry()
        await self.capture(fail=True)
        final=await self.row()
        self.assertTrue(final.processing_deferred)
        self.assertEqual(final.retry_count,3)
        await self.scheduler._auto_retry_failed_downloads()
        await self.finish()
        final=await self.row()
        self.assertEqual(self.processed,[str(old)])
        self.assertTrue(Path(final.output_path).exists())
        self.assertIsNone(final.retained_captures_json)

    async def test_master_off_finalizes_without_recapture(self):
        await self.capture()
        await self.settings(auto_retry_failed_downloads=False)
        await self.scheduler._auto_retry_failed_downloads()
        await self.finish()
        self.assertEqual((await self.row()).retry_count,0)
        self.assertTrue(self.manager._queue.empty())
        self.assertEqual(len(self.processed),1)

    async def test_classification_off_finalizes_as_interrupted(self):
        await self.capture()
        await self.settings(mark_short_downloads_failed=False)
        await self.scheduler._auto_retry_failed_downloads()
        await self.finish()
        self.assertEqual((await self.row()).status,'interrupted')
        self.assertTrue(self.manager._queue.empty())

    async def test_short_classification_without_master_never_retries(self):
        await self.settings(auto_retry_failed_downloads=False)
        await self.capture()
        await self.finish()
        await self.age()
        await self.scheduler._auto_retry_failed_downloads()
        self.assertEqual((await self.row()).status,'failed')
        self.assertTrue(self.manager._queue.empty())
        self.assertEqual(len(self.processed),1)

    async def test_archive_expired_finalizes_but_unreachable_provider_waits(self):
        await self.capture()
        await self.age()
        self.archive.side_effect=RuntimeError('unreachable')
        await self.scheduler._auto_retry_failed_downloads()
        self.assertTrue((await self.row()).processing_deferred)
        self.assertTrue(self.manager._post_queue.empty())
        self.archive.side_effect=None
        self.archive.return_value=0
        await self.scheduler._auto_retry_failed_downloads()
        await self.finish()
        self.assertEqual((await self.row()).retry_count,0)

    async def test_processing_error_keeps_all_fallbacks(self):
        old=await self.capture()
        await self.retry()
        latest=await self.capture(60)
        self.processor.side_effect=RuntimeError('Comskip error')
        await self.finish()
        self.assertEqual((await self.row()).status,'failed')
        self.assertTrue(old.exists())
        self.assertTrue(latest.exists())
        self.assertIsNotNone((await self.row()).retained_captures_json)

    async def test_processing_warning_preserves_fallbacks_on_restart(self):
        old=await self.capture()
        await self.retry()
        await self.capture(60)
        self.processor.side_effect=None
        latest=(await self.row()).output_path
        self.processor.return_value=(latest,['Conversion failed'])
        await self.finish()
        await self.manager.recover_retained_cleanup()
        self.assertTrue(old.exists())
        self.assertIsNotNone((await self.row()).retained_captures_json)

    async def test_move_error_keeps_retained_files(self):
        old=await self.capture()
        await self.retry()
        await self.capture(60)
        with patch.object(self.manager,'_move_to_completed_async',AsyncMock(side_effect=OSError('full'))):
            await self.finish()
        self.assertTrue(old.exists())
        self.assertFalse((await self.row()).retry_finalized)

    async def test_final_validation_failure_keeps_fallbacks(self):
        old=await self.capture()
        await self.retry()
        await self.capture(60)
        with patch.object(self.manager,'_partial_is_playable',AsyncMock(return_value=False)):
            await self.finish()
        self.assertTrue(old.exists())
        self.assertIn('could not be verified',(await self.row()).error_message)

    async def test_changed_owned_file_is_not_deleted(self):
        old=await self.capture()
        await self.retry()
        old.write_bytes(b'replaced or modified by somebody else')
        await self.capture(60)
        await self.finish()
        self.assertEqual(old.read_bytes(),b'replaced or modified by somebody else')
        self.assertIn('changed',(await self.row()).error_message)

    async def test_unrelated_and_other_recording_files_are_protected(self):
        old=await self.capture()
        unrelated=self.raw/'show - retry 999.ts'
        unrelated.write_bytes(b'unrelated')
        async with self.sessions() as session:
            session.add(recording(old,program_title='Other owner'))
            await session.commit()
        await self.retry()
        await self.capture(60)
        await self.finish()
        self.assertTrue(old.exists())
        self.assertEqual(unrelated.read_bytes(),b'unrelated')

    async def test_keep_original_only_preserves_selected_not_all_retries(self):
        old=await self.capture()
        await self.retry()
        await self.settings(auto_retry_failed_downloads=False,delete_original_after_transcode=False)
        chosen=await self.capture()
        await self.finish()
        self.assertFalse(old.exists())
        self.assertTrue(chosen.exists())
        self.assertTrue(Path((await self.row()).output_path).exists())
        self.assertIsNone((await self.row()).retained_captures_json)

    async def test_keep_ts_finalizes_and_cleans_without_other_processing(self):
        old=await self.capture()
        await self.retry()
        await self.settings(transcode_enabled=False)
        await self.capture(60)
        final=await self.row()
        self.assertEqual(final.status,'completed')
        self.assertEqual(self.processed,[])
        self.assertTrue(Path(final.output_path).exists())
        self.assertFalse(old.exists())

    async def test_restart_resumes_post_commit_cleanup_without_processing_again(self):
        old=await self.capture()
        await self.retry()
        await self.capture(60)
        with patch.object(self.manager,'_cleanup_retained_attempts',AsyncMock()):
            await self.finish()
        self.assertTrue(old.exists())
        await self.manager.recover_retained_cleanup()
        self.assertFalse(old.exists())
        self.assertEqual(len(self.processed),1)
        self.assertIsNone((await self.row()).retained_captures_json)

    async def test_salvaged_short_output_stays_failed_and_does_not_claim_cleanup_safety(self):
        from services.recording_events import RECORDING_FAILED
        await self.capture()
        row=await self.row()
        final=self.completed/'survived.ts'
        final.write_bytes(Path(row.output_path).read_bytes())
        with patch('services.download_manager.recording_events.publish') as publish:
            async with self.sessions() as session:
                await self.manager._finalize_completed_after_interrupt(
                    session,self.download.id,str(final),status='failed')
            self.assertEqual(publish.call_args.args[0],RECORDING_FAILED)
        refreshed=await self.row()
        self.assertTrue(refreshed.short_file_failed)
        self.assertTrue(refreshed.retry_finalized)
        self.assertFalse(refreshed.processing_deferred)
        await self.manager.recover_retained_cleanup()
        self.assertTrue(Path(row.output_path).exists())
        self.assertTrue(final.exists())

    async def test_failed_final_file_can_be_served_but_deferred_file_cannot(self):
        from api.downloads import get_download_file
        from auth import AuthContext
        from fastapi import HTTPException
        from starlette.responses import FileResponse
        auth=AuthContext(authenticated=True,is_admin=True,user_id=1)
        await self.capture()
        async with self.sessions() as session:
            with self.assertRaises(HTTPException) as error:
                await get_download_file(self.download.id,None,"download",auth,session)
            self.assertEqual(error.exception.status_code,409)
        await self.settings(auto_retry_failed_downloads=False)
        await self.scheduler._auto_retry_failed_downloads()
        await self.finish()
        async with self.sessions() as session:
            result=await get_download_file(self.download.id,None,"download",auth,session)
            self.assertIsInstance(result,FileResponse)

    async def test_clear_finished_preserves_deferred_ownership(self):
        from api.downloads import clear_finished_downloads
        from auth import AuthContext
        auth=AuthContext(authenticated=True,is_admin=True,user_id=1)
        old=await self.capture()
        async with self.sessions() as session:
            await clear_finished_downloads(auth,session)
        self.assertIsNotNone(await self.row())
        self.assertTrue(old.exists())

    async def test_cleanup_error_is_retryable_without_reprocessing(self):
        old=await self.capture()
        await self.retry()
        await self.capture(60)
        real_unlink=retained_captures.os.unlink
        def reject(path,*args,**kwargs):
            if str(path)==str(old):
                raise PermissionError("busy")
            return real_unlink(path,*args,**kwargs)
        with patch('services.retained_captures.os.unlink',side_effect=reject):
            await self.finish()
        self.assertTrue(old.exists())
        self.assertIn('cleanup',(await self.row()).error_message)
        await self.manager.recover_retained_cleanup()
        self.assertFalse(old.exists())
        self.assertEqual(len(self.processed),1)

    async def test_expired_policy_recheck_cannot_queue_after_cancellation(self):
        await self.capture()
        await self.age()
        async def cancel_probe(path):
            self.manager._cancelled.add(self.download.id)
            return True
        with patch.object(self.manager,'_partial_is_playable',AsyncMock(side_effect=cancel_probe)):
            self.assertFalse(await self.manager.finalize_deferred_capture(self.download.id,recovery_unavailable=True))
        self.assertTrue(self.manager._post_queue.empty())

    async def test_cancellation_preserves_deferred_file_and_stops_retries(self):
        old=await self.capture()
        self.assertTrue(await self.manager.cancel_download(self.download.id))
        await self.age()
        await self.scheduler._auto_retry_failed_downloads()
        self.assertEqual((await self.row()).status,'cancelled')
        self.assertTrue(old.exists())
        self.assertTrue(self.manager._queue.empty())

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg required')
    async def test_real_media_four_short_attempts_keep_one_final_file(self):
        fixture=self.root/'fixture.ts'
        subprocess.run([shutil.which('ffmpeg'),'-hide_banner','-loglevel','error','-f','lavfi',
            '-i','color=c=black:s=32x32:r=1','-t','50','-c:v','mpeg2video','-an','-f','mpegts',str(fixture)],
            check=True,timeout=15,capture_output=True)
        media=fixture.read_bytes()
        fixture.unlink()
        from services.post_processor import post_processor
        # Use actual probing and actual postprocessing, isolating network only.
        self.stack.close()
        with ExitStack() as stack:
            stack.enter_context(patch('services.download_manager.async_session_maker',self.sessions))
            stack.enter_context(patch('services.scheduled_manager.async_session_maker',self.sessions))
            stack.enter_context(patch('services.scheduled_manager.download_manager',self.manager))
            stack.enter_context(patch.object(self.scheduler,'_get_free_space_gb',AsyncMock(return_value=1000)))
            stack.enter_context(patch.object(self.scheduler,'_get_archive_days_raw',AsyncMock(return_value=7)))
            stack.enter_context(patch.object(self.manager,'_trigger_plex_refresh',AsyncMock()))
            await self.settings(transcode_enabled=False)
            for attempt in range(4):
                row=await self.row()
                async def transfer(*args,**kwargs):
                    Path(row.output_path).write_bytes(media)
                    return len(media)
                with patch.object(self.manager,'_download_catchup_stream',AsyncMock(side_effect=transfer)):
                    await self.manager._execute_download(row.id)
                if attempt<3:
                    self.assertTrue((await self.row()).processing_deferred)
                    await self.retry()
            final=await self.row()
            self.assertEqual(final.status,'failed')
            self.assertTrue(final.retry_finalized)
            self.assertEqual(final.retry_count,3)
            self.assertAlmostEqual(final.raw_duration_seconds,50,delta=1)
            self.assertEqual(Path(final.output_path).read_bytes(),media)
            self.assertEqual(len([p for p in self.root.rglob('*') if p.is_file()]),1)


class RetainedIdentityTests(unittest.TestCase):
    def test_symlink_replacement_is_never_deleted(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'owned.ts'
            target=Path(folder)/'other.ts'
            path.write_bytes(b'owned')
            receipt=retained_captures.identity(str(path))
            path.unlink()
            target.write_bytes(b'other')
            path.symlink_to(target)
            remaining,warnings=retained_captures.cleanup({'attempts':[{'media':receipt}]},[],False)
            self.assertTrue(path.is_symlink())
            self.assertTrue(target.exists())
            self.assertTrue(warnings)
            self.assertTrue(remaining['attempts'])

    def test_only_registered_companions_are_removed(self):
        with tempfile.TemporaryDirectory() as folder:
            media=Path(folder)/'old.ts'
            companion=media.with_suffix('.edl')
            unrelated=media.with_suffix('.log')
            for p in (media,companion,unrelated): p.write_bytes(b'data')
            value={'attempts':[{'media':retained_captures.identity(str(media)),
                'companions':[retained_captures.identity(str(companion))]}]}
            remaining,errors=retained_captures.cleanup(value,[],False)
            self.assertFalse(media.exists())
            self.assertFalse(companion.exists())
            self.assertTrue(unrelated.exists())
            self.assertEqual(remaining['attempts'],[])
            self.assertEqual(errors,[])


class RetrySettingMigrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_switch_migrates_once_without_enabling_master(self):
        engine=create_async_engine('sqlite+aiosqlite:///:memory:')
        try:
            async with engine.begin() as conn:
                for table in ('plex_servers','app_settings','epg_programs','xtream_accounts','scheduled_recordings','downloads'):
                    await conn.execute(text(f'CREATE TABLE {table} (id INTEGER PRIMARY KEY)'))
                await conn.execute(text('ALTER TABLE app_settings ADD COLUMN auto_retry_short_downloads BOOLEAN DEFAULT 0'))
                await conn.execute(text('INSERT INTO app_settings(id,auto_retry_short_downloads) VALUES (1,1)'))
                await _apply_lightweight_migrations(conn)
                vals=(await conn.execute(text('SELECT mark_short_downloads_failed,auto_retry_failed_downloads FROM app_settings'))).one()
                self.assertEqual(tuple(vals),(1,0))
                await conn.execute(text('UPDATE app_settings SET mark_short_downloads_failed=0'))
                await _apply_lightweight_migrations(conn)
                self.assertEqual((await conn.execute(text('SELECT mark_short_downloads_failed FROM app_settings'))).scalar_one(),0)
        finally:
            await engine.dispose()
