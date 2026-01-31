import asyncio
import aiohttp
import aiofiles
import os
from datetime import datetime
from typing import Optional, Callable, Dict, Set
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from models import Download, DownloadStatus, AppSettings
from database import async_session_maker


class DownloadManager:
    def __init__(self):
        self._queue: asyncio.Queue = asyncio.Queue()
        self._active_downloads: Dict[int, asyncio.Task] = {}
        self._cancelled: Set[int] = set()
        self._progress_callbacks: Dict[int, Callable] = {}
        self._websocket_connections: Set = set()
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

        dead_connections = set()
        for ws in self._websocket_connections:
            try:
                await ws.send_json(message)
            except Exception:
                dead_connections.add(ws)

        # Clean up dead connections
        self._websocket_connections -= dead_connections

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
        indeterminate: bool = False
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
            indeterminate=indeterminate
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
                final_path = await self._post_process(download.output_path, download_id, session)
                if final_path != download.output_path:
                    download.output_path = final_path

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
                                file_size=total_size
                            )

    async def _post_process(self, file_path: str, download_id: int, session: AsyncSession) -> str:
        """Run post-processing on downloaded file (transcoding, commercial removal)."""
        from services.post_processor import post_processor, OutputFormat, HardwareAccel

        # Get settings
        result = await session.execute(select(AppSettings))
        settings = result.scalar_one_or_none()

        if not settings:
            return file_path

        current_path = file_path

        if settings.comskip_path:
            post_processor.set_comskip_path(settings.comskip_path)
            try:
                if os.name == "posix" and os.uname().sysname == "Linux":
                    from pathlib import Path
                    comskip_dir = Path(settings.comskip_path).resolve().parent
                    for name in ("ffmpeg", "ffmpeg.exe"):
                        ffmpeg_candidate = comskip_dir / name
                        if ffmpeg_candidate.is_file() and os.access(ffmpeg_candidate, os.X_OK):
                            post_processor.set_ffmpeg_path(str(ffmpeg_candidate))
                            break
            except Exception:
                pass

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
            return current_path

        async def log_callback(message: str):
            await self._broadcast_log(download_id, message)

        if settings.comskip_enabled and not post_processor.comskip_available:
            await log_callback("Comskip enabled but not available; skipping detection.")
        if settings.transcode_enabled and not post_processor.ffmpeg_available:
            await log_callback("Transcoding enabled but ffmpeg not available; skipping transcode.")

        await self._update_processing(session, download_id, 0, "Starting post-processing...")
        await log_callback("Post-processing started.")
        last_progress = -1.0
        current_message = None

        async def progress_callback(p: float):
            nonlocal last_progress
            if p - last_progress >= 1 or p >= 100:
                last_progress = p
                await self._update_processing(session, download_id, p, current_message)

        # log_callback defined above to also persist logs

        commercials_removed = False

        # Run Comskip if enabled
        if will_comskip:
            try:
                current_message = "Detecting commercials..."
                await self._update_processing(session, download_id, 1, current_message, indeterminate=True)
                await log_callback("Comskip: detecting commercials.")

                if settings.comskip_path:
                    post_processor.set_comskip_path(settings.comskip_path)

                ffmpeg_path = post_processor.get_ffmpeg_path()
                if ffmpeg_path:
                    await log_callback(f"ffmpeg resolved: {ffmpeg_path}")

                edl_path = await post_processor.detect_commercials(
                    current_path,
                    settings.comskip_ini_path,
                    log_callback=log_callback
                )

                if edl_path and settings.remove_commercials:
                    output_format = OutputFormat(settings.transcode_format) if settings.transcode_enabled else OutputFormat.TS
                    current_message = f"Removing commercials + transcoding to {output_format.value} (using {hw_accel.value})..."
                    await self._update_processing(session, download_id, 5, current_message)
                    await log_callback(
                        f"Comskip: commercials detected. Removing commercials and outputting {output_format.value}."
                    )

                    current_path = await post_processor.remove_commercials(
                        current_path,
                        edl_path,
                        output_format,
                        hw_accel=hw_accel,
                        remove_original=settings.delete_original_after_transcode,
                        progress_callback=progress_callback,
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
                print(f"Comskip error (continuing anyway): {e}")

        # Transcode if enabled (and not already done by commercial removal)
        if will_transcode and not commercials_removed:
            try:
                accel_name = hw_accel.value if hw_accel != HardwareAccel.CPU else "CPU"
                current_message = f"Transcoding to {settings.transcode_format} (using {accel_name})..."
                await self._update_processing(session, download_id, 5, current_message)
                await log_callback(
                    f"Transcoding started: {settings.transcode_format} with {accel_name}."
                )

                output_format = OutputFormat(settings.transcode_format)
                current_path = await post_processor.transcode(
                    current_path,
                    output_format,
                    hw_accel=hw_accel,
                    quality=quality,
                    progress_callback=progress_callback,
                    log_callback=log_callback,
                    remove_original=settings.delete_original_after_transcode,
                    remux_only=remux_only
                )
                await log_callback(f"Transcoding complete: {current_path}")
            except Exception as e:
                await log_callback(f"Transcode error: {e}")
                print(f"Transcode error (continuing anyway): {e}")

        return current_path

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
            return [d.to_dict() for d in result.scalars().all()]

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
            return [d.to_dict() for d in result.scalars().all()]


# Global instance
download_manager = DownloadManager()
