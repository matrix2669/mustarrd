import asyncio
import aiohttp
import aiofiles
import os
import shutil
from pathlib import Path
from datetime import datetime
from typing import Optional, Callable, Dict, Set, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from models import Download, DownloadStatus, AppSettings
from config import settings as app_settings
from database import async_session_maker


class DownloadManager:
    def __init__(self):
        self._queue: asyncio.Queue = asyncio.Queue()
        self._active_downloads: Dict[int, asyncio.Task] = {}
        self._cancelled: Set[int] = set()
        self._progress_callbacks: Dict[int, Callable] = {}
        self._websocket_connections: Set = set()
        self._stage_progress: Dict[int, Dict[str, Any]] = {}
        self._max_concurrent = 2
        self._running = False

    def set_max_concurrent(self, max_concurrent: int):
        self._max_concurrent = max_concurrent

    def register_websocket(self, websocket):
        self._websocket_connections.add(websocket)

    def unregister_websocket(self, websocket):
        self._websocket_connections.discard(websocket)

    async def _broadcast_progress(self, download_id: int, progress: float, status: str, **extra):
        """Broadcast progress to all connected WebSocket clients."""
        message = {
            "type": "progress",
            "download_id": download_id,
            "progress": progress,
            "status": status,
            **extra
        }
        snapshot = self._stage_progress.get(download_id, {})
        for key, value in message.items():
            if key in ("type", "download_id"):
                continue
            if value is not None:
                snapshot[key] = value
        self._stage_progress[download_id] = snapshot

        dead_connections = set()
        for ws in self._websocket_connections:
            try:
                await ws.send_json(message)
            except Exception:
                dead_connections.add(ws)

        # Clean up dead connections
        self._websocket_connections -= dead_connections
        if status in [
            DownloadStatus.COMPLETED.value,
            DownloadStatus.FAILED.value,
            DownloadStatus.CANCELLED.value
        ]:
            self._stage_progress.pop(download_id, None)

    def merge_progress_snapshot(self, data: dict) -> dict:
        """Merge in-memory progress fields into a download dict."""
        snapshot = self._stage_progress.get(data.get("id"))
        if not snapshot:
            return data
        return {**data, **snapshot}

    async def _broadcast_log(self, download_id: int, message: str, level: str = "info"):
        """Broadcast a log line to all connected WebSocket clients."""
        payload = {
            "type": "log",
            "download_id": download_id,
            "level": level,
            "message": message,
        }

        dead_connections = set()
        for ws in self._websocket_connections:
            try:
                await ws.send_json(payload)
            except Exception:
                dead_connections.add(ws)

        self._websocket_connections -= dead_connections

    async def _update_processing(
        self,
        session: AsyncSession,
        download_id: int,
        progress: float,
        message: Optional[str] = None,
        indeterminate: bool = False,
        **extra
    ):
        """Update processing status/progress and broadcast to clients."""
        await session.execute(
            update(Download)
            .where(Download.id == download_id)
            .values(
                status=DownloadStatus.PROCESSING.value,
                progress=progress
            )
        )
        await session.commit()

        await self._broadcast_progress(
            download_id,
            progress,
            DownloadStatus.PROCESSING.value,
            message=message,
            indeterminate=indeterminate,
            **extra
        )

    async def queue_download(self, download: Download) -> Download:
        """Add a download to the queue."""
        async with async_session_maker() as session:
            session.add(download)
            await session.commit()
            await session.refresh(download)

            await self._queue.put(download.id)
            return download

    async def process_queue(self):
        """Main loop for processing download queue."""
        self._running = True

        while self._running:
            try:
                # Wait for active downloads to have space
                while len(self._active_downloads) >= self._max_concurrent:
                    await asyncio.sleep(0.5)
                    # Clean up completed tasks
                    completed = [
                        did for did, task in self._active_downloads.items()
                        if task.done()
                    ]
                    for did in completed:
                        del self._active_downloads[did]

                # Get next download from queue
                try:
                    download_id = await asyncio.wait_for(
                        self._queue.get(),
                        timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue

                # Skip if cancelled
                if download_id in self._cancelled:
                    self._cancelled.discard(download_id)
                    continue

                # Start download task
                task = asyncio.create_task(self._execute_download(download_id))
                self._active_downloads[download_id] = task

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Error in queue processor: {e}")
                await asyncio.sleep(1)

    async def _execute_download(self, download_id: int):
        """Execute a single download."""
        async with async_session_maker() as session:
            try:
                # Get download record
                result = await session.execute(
                    select(Download).where(Download.id == download_id)
                )
                download = result.scalar_one_or_none()

                if not download:
                    return

                # Check if cancelled
                if download_id in self._cancelled:
                    self._cancelled.discard(download_id)
                    return

                # Update status to downloading
                download.status = DownloadStatus.DOWNLOADING.value
                await session.commit()

                await self._broadcast_progress(
                    download_id, 0, DownloadStatus.DOWNLOADING.value
                )

                # Ensure output directory exists
                output_dir = os.path.dirname(download.output_path)
                os.makedirs(output_dir, exist_ok=True)

                # Start download
                await self._download_file(
                    download.source_url,
                    download.output_path,
                    download_id,
                    session
                )

                # Run post-processing if enabled
                original_path = download.output_path
                settings_result = await session.execute(select(AppSettings))
                settings = settings_result.scalar_one_or_none()
                final_path, warnings = await self._post_process(
                    download.output_path,
                    download_id,
                    session,
                    settings
                )
                completed_folder = self._resolve_completed_folder(settings)
                download_folder = self._resolve_download_folder(settings)
                final_path = self._select_final_path(original_path, final_path)
                completed_path = self._move_to_completed(final_path, completed_folder, download_folder)
                download.output_path = completed_path
                if warnings:
                    download.error_message = f"Completed with warnings: {'; '.join(warnings)}"
                else:
                    download.error_message = None
                self._cleanup_working_files(
                    original_path,
                    completed_path,
                    keep_logs=bool(warnings)
                )

                # Mark as completed
                download.status = DownloadStatus.COMPLETED.value
                download.progress = 100.0
                download.completed_at = datetime.utcnow()
                await session.commit()

                await self._broadcast_progress(
                    download_id, 100, DownloadStatus.COMPLETED.value
                )

            except asyncio.CancelledError:
                # Download was cancelled
                download.status = DownloadStatus.CANCELLED.value
                await session.commit()
                await self._broadcast_progress(
                    download_id, download.progress, DownloadStatus.CANCELLED.value
                )

            except Exception as e:
                # Download failed
                result = await session.execute(
                    select(Download).where(Download.id == download_id)
                )
                download = result.scalar_one_or_none()
                if download:
                    download.status = DownloadStatus.FAILED.value
                    download.error_message = str(e)
                    await session.commit()

                await self._broadcast_progress(
                    download_id,
                    download.progress if download else 0,
                    DownloadStatus.FAILED.value,
                    error=str(e)
                )

    def _resolve_completed_folder(self, settings: Optional[AppSettings]) -> str:
        if settings and settings.completed_folder and not settings.completed_folder.startswith("./data"):
            return settings.completed_folder
        return app_settings.default_completed_folder

    def _resolve_download_folder(self, settings: Optional[AppSettings]) -> str:
        if settings and settings.download_folder and not settings.download_folder.startswith("./data"):
            return settings.download_folder
        return app_settings.default_download_folder

    def _select_final_path(self, original_path: str, final_path: str) -> str:
        if final_path and os.path.exists(final_path):
            return final_path
        if os.path.exists(original_path):
            return original_path
        raise Exception("No output file available to move to completed folder.")

    def _move_to_completed(self, path: str, completed_folder: str, download_folder: Optional[str] = None) -> str:
        if download_folder:
            try:
                common = os.path.commonpath([os.path.abspath(path), os.path.abspath(download_folder)])
            except Exception:
                common = None
            if common and os.path.abspath(common) == os.path.abspath(download_folder):
                rel = os.path.relpath(path, download_folder)
                dest = os.path.join(completed_folder, rel)
            else:
                dest = os.path.join(completed_folder, os.path.basename(path))
        else:
            dest = os.path.join(completed_folder, os.path.basename(path))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        if os.path.abspath(path) == os.path.abspath(dest):
            return path
        shutil.move(path, dest)
        return dest

    def _cleanup_working_files(self, original_path: str, completed_path: str, keep_logs: bool) -> None:
        try:
            original_file = Path(original_path)
            base_dir = original_file.parent
            stem = original_file.stem

            if original_path != completed_path and original_file.exists():
                original_file.unlink()

            patterns = [
                f"{stem}_seg*.ts",
                f"{stem}.concat.txt",
                f"{stem}_nocommercials.*",
                f"{stem}.edl",
                f"{stem}.txt",
                f"{stem}.logo",
                f"{stem}.csv",
                f"{stem}.vdr",
                f"{stem}.xml",
                f"{stem}.srt",
                f"{stem}.ass",
                f"{stem}.vtt",
            ]
            if not keep_logs:
                patterns.extend([
                    f"{stem}.log",
                    f"{stem}.*.ffmpeg.log",
                ])

            for pattern in patterns:
                for path in base_dir.glob(pattern):
                    try:
                        path.unlink()
                    except Exception:
                        continue
        except Exception:
            pass

    async def _download_file(
        self,
        url: str,
        output_path: str,
        download_id: int,
        session: AsyncSession
    ):
        """Stream download a file with progress tracking."""
        timeout = aiohttp.ClientTimeout(total=None, sock_read=60)

        async with aiohttp.ClientSession(timeout=timeout) as http_session:
            async with http_session.get(url) as response:
                if response.status != 200:
                    raise Exception(f"HTTP {response.status}: {response.reason}")

                total_size = response.content_length or 0
                downloaded = 0
                last_progress_update = 0

                async with aiofiles.open(output_path, 'wb') as f:
                    async for chunk in response.content.iter_chunked(1024 * 1024):  # 1MB chunks
                        # Check for cancellation
                        if download_id in self._cancelled:
                            raise asyncio.CancelledError()

                        await f.write(chunk)
                        downloaded += len(chunk)

                        # Update progress every 1%
                        if total_size > 0:
                            progress = (downloaded / total_size) * 100
                        else:
                            progress = 0

                        if progress - last_progress_update >= 1 or downloaded == total_size:
                            last_progress_update = progress

                            # Update database
                            await session.execute(
                                update(Download)
                                .where(Download.id == download_id)
                                .values(
                                    progress=progress,
                                    downloaded_bytes=downloaded,
                                    file_size=total_size
                                )
                            )
                            await session.commit()

                            # Broadcast progress
                            await self._broadcast_progress(
                                download_id,
                                progress,
                                DownloadStatus.DOWNLOADING.value,
                                downloaded_bytes=downloaded,
                                file_size=total_size,
                                download_progress=progress
                            )

    async def _post_process(
        self,
        file_path: str,
        download_id: int,
        session: AsyncSession,
        settings: Optional[AppSettings] = None
    ) -> tuple[str, list[str]]:
        """Run post-processing on downloaded file (transcoding, commercial removal)."""
        from services.post_processor import post_processor, OutputFormat, HardwareAccel

        warnings: list[str] = []

        if not settings:
            return file_path, warnings

        current_path = file_path

        if settings.comskip_path:
            post_processor.set_comskip_path(settings.comskip_path)

        # Get hardware acceleration setting
        try:
            hw_accel = HardwareAccel(settings.hw_accel) if settings.hw_accel else HardwareAccel.CPU
        except ValueError:
            hw_accel = HardwareAccel.CPU

        quality = settings.transcode_quality if hasattr(settings, 'transcode_quality') else "balanced"
        remux_only = getattr(settings, "remux_only", False)

        will_comskip = settings.comskip_enabled and post_processor.comskip_available
        will_transcode = settings.transcode_enabled and post_processor.ffmpeg_available

        if not will_comskip and not will_transcode:
            return current_path, warnings

        async def log_callback(message: str):
            await self._broadcast_log(download_id, message)

        if settings.comskip_enabled and not post_processor.comskip_available:
            await log_callback("Comskip enabled but not available; skipping detection.")
        if settings.transcode_enabled and not post_processor.ffmpeg_available:
            await log_callback("Transcoding enabled but ffmpeg not available; skipping transcode.")

        download_progress = 100.0
        comskip_progress: Optional[float] = None
        transcode_progress: Optional[float] = None
        comskip_indeterminate = False
        transcode_indeterminate = False

        async def broadcast_processing(progress: float, message: Optional[str], indeterminate: bool = False):
            await self._update_processing(
                session,
                download_id,
                progress,
                message,
                indeterminate=indeterminate,
                download_progress=download_progress,
                comskip_progress=comskip_progress,
                transcode_progress=transcode_progress,
                comskip_indeterminate=comskip_indeterminate,
                transcode_indeterminate=transcode_indeterminate
            )

        await broadcast_processing(0, "Starting post-processing...")
        await log_callback("Post-processing started.")
        last_progress = -1.0
        current_message = None

        async def transcode_progress_callback(p: float):
            nonlocal last_progress
            nonlocal transcode_progress
            if p - last_progress >= 1 or p >= 100:
                last_progress = p
                transcode_progress = p
                await broadcast_processing(p, current_message, indeterminate=transcode_indeterminate)

        # log_callback defined above to also persist logs

        commercials_removed = False

        # Run Comskip if enabled
        if will_comskip:
            try:
                current_message = "Detecting commercials..."
                comskip_progress = 0.0
                comskip_indeterminate = True
                await broadcast_processing(comskip_progress, current_message, indeterminate=True)
                await log_callback("Comskip: detecting commercials.")

                if settings.comskip_path:
                    post_processor.set_comskip_path(settings.comskip_path)

                ffmpeg_path = post_processor.get_ffmpeg_path()
                if ffmpeg_path:
                    await log_callback(f"ffmpeg resolved: {ffmpeg_path}")

                async def comskip_progress_callback(p: float):
                    nonlocal comskip_progress, comskip_indeterminate
                    comskip_progress = p
                    comskip_indeterminate = False
                    await broadcast_processing(comskip_progress, current_message, indeterminate=False)

                edl_path = await post_processor.detect_commercials(
                    current_path,
                    settings.comskip_ini_path,
                    log_callback=log_callback,
                    progress_callback=comskip_progress_callback
                )
                if comskip_progress is None or comskip_progress < 100:
                    comskip_progress = 100.0
                comskip_indeterminate = False
                await broadcast_processing(comskip_progress, current_message, indeterminate=False)

                if edl_path and settings.remove_commercials:
                    output_format = OutputFormat(settings.transcode_format) if settings.transcode_enabled else OutputFormat.TS
                    current_message = f"Removing commercials + transcoding to {output_format.value} (using {hw_accel.value})..."
                    transcode_progress = 0.0
                    transcode_indeterminate = False
                    await broadcast_processing(transcode_progress, current_message)
                    await log_callback(
                        f"Comskip: commercials detected. Removing commercials and outputting {output_format.value}."
                    )

                    current_path = await post_processor.remove_commercials(
                        current_path,
                        edl_path,
                        output_format,
                        hw_accel=hw_accel,
                        remove_original=settings.delete_original_after_transcode,
                        progress_callback=transcode_progress_callback,
                        log_callback=log_callback,
                        remux_only=False
                    )
                    commercials_removed = True
                    await log_callback(f"Commercial removal complete: {current_path}")
                elif edl_path:
                    await log_callback("Comskip: commercials detected but removal disabled.")
                else:
                    await log_callback("Comskip: no commercials detected.")
            except Exception as e:
                await log_callback(f"Comskip error: {e}")
                warnings.append(f"Comskip failed: {e}")
                print(f"Comskip error (continuing anyway): {e}")

        # Transcode if enabled (and not already done by commercial removal)
        if will_transcode and not commercials_removed:
            try:
                accel_name = hw_accel.value if hw_accel != HardwareAccel.CPU else "CPU"
                current_message = f"Transcoding to {settings.transcode_format} (using {accel_name})..."
                transcode_progress = 0.0
                transcode_indeterminate = False
                await broadcast_processing(transcode_progress, current_message)
                await log_callback(
                    f"Transcoding started: {settings.transcode_format} with {accel_name}."
                )

                output_format = OutputFormat(settings.transcode_format)
                current_path = await post_processor.transcode(
                    current_path,
                    output_format,
                    hw_accel=hw_accel,
                    quality=quality,
                    progress_callback=transcode_progress_callback,
                    log_callback=log_callback,
                    remove_original=settings.delete_original_after_transcode,
                    remux_only=remux_only
                )
                await log_callback(f"Transcoding complete: {current_path}")
            except Exception as e:
                await log_callback(f"Transcode error: {e}")
                warnings.append(f"Transcode failed: {e}")
                print(f"Transcode error (continuing anyway): {e}")

        return current_path, warnings

    async def cancel_download(self, download_id: int) -> bool:
        """Cancel a download."""
        self._cancelled.add(download_id)

        # Cancel active task if running
        if download_id in self._active_downloads:
            self._active_downloads[download_id].cancel()
            return True

        # Update database status if pending
        async with async_session_maker() as session:
            result = await session.execute(
                select(Download).where(Download.id == download_id)
            )
            download = result.scalar_one_or_none()

            if download and download.status == DownloadStatus.PENDING.value:
                download.status = DownloadStatus.CANCELLED.value
                await session.commit()
                return True

        return False

    async def retry_download(self, download_id: int) -> bool:
        """Retry a failed download."""
        async with async_session_maker() as session:
            result = await session.execute(
                select(Download).where(Download.id == download_id)
            )
            download = result.scalar_one_or_none()

            if download and download.status in [
                DownloadStatus.FAILED.value,
                DownloadStatus.CANCELLED.value
            ]:
                download.status = DownloadStatus.PENDING.value
                download.progress = 0
                download.downloaded_bytes = 0
                download.error_message = None
                await session.commit()

                await self._queue.put(download_id)
                return True

        return False

    async def get_queue(self) -> list:
        """Get pending and downloading downloads."""
        async with async_session_maker() as session:
            result = await session.execute(
                select(Download).where(
                    Download.status.in_([
                        DownloadStatus.PENDING.value,
                        DownloadStatus.DOWNLOADING.value,
                        DownloadStatus.PROCESSING.value
                    ])
                ).order_by(Download.created_at)
            )
            return [self.merge_progress_snapshot(d.to_dict()) for d in result.scalars().all()]

    async def get_history(self) -> list:
        """Get completed and failed downloads."""
        async with async_session_maker() as session:
            result = await session.execute(
                select(Download).where(
                    Download.status.in_([
                        DownloadStatus.COMPLETED.value,
                        DownloadStatus.FAILED.value,
                        DownloadStatus.CANCELLED.value
                    ])
                ).order_by(Download.created_at.desc())
            )
            return [self.merge_progress_snapshot(d.to_dict()) for d in result.scalars().all()]


# Global instance
download_manager = DownloadManager()
