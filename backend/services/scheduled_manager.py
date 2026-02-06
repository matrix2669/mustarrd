import asyncio
from datetime import datetime, timezone

from sqlalchemy import select
from database import async_session_maker
from models import ScheduledRecording, ScheduledStatus, AppSettings
from services.download_builder import build_download_from_program
from services.download_manager import download_manager
from config import settings as app_settings
import os
import shutil


class ScheduledManager:
    def __init__(self):
        self._running = False
        self._poll_interval = 30

    async def process_queue(self):
        self._running = True

        while self._running:
            try:
                await self._queue_ready_recordings()
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Error in schedule processor: {e}")
            await asyncio.sleep(self._poll_interval)

    async def _queue_ready_recordings(self):
        now_utc = datetime.utcnow().replace(tzinfo=timezone.utc)
        async with async_session_maker() as session:
            result = await session.execute(
                select(ScheduledRecording).where(
                    ScheduledRecording.status.in_(
                        [
                            ScheduledStatus.SCHEDULED.value,
                            ScheduledStatus.PAUSED_LOW_SPACE.value,
                        ]
                    )
                )
            )
            schedules = result.scalars().all()

            if not schedules:
                return

            settings_result = await session.execute(select(AppSettings))
            settings = settings_result.scalar_one_or_none()
            download_folder = settings.download_folder if settings and settings.download_folder else app_settings.default_download_folder
            min_free_gb = settings.min_free_space_gb if settings and settings.min_free_space_gb is not None else 25

            ready = []
            for schedule in schedules:
                available_at = schedule.available_at_utc()
                if not available_at:
                    continue
                if available_at <= now_utc:
                    ready.append(schedule)

            if not ready:
                return

            free_gb = self._get_free_space_gb(download_folder)

            for schedule in ready:
                if free_gb < min_free_gb:
                    schedule.status = ScheduledStatus.PAUSED_LOW_SPACE.value
                    schedule.status_message = (
                        f"Waiting for free space ({free_gb:.1f} GB free, "
                        f"{min_free_gb} GB required)."
                    )
                    schedule.updated_at = datetime.utcnow()
                    continue

                try:
                    program = {
                        "title": schedule.program_title,
                        "description": schedule.program_description or "",
                        "start_time": schedule.program_start.isoformat() if schedule.program_start else None,
                        "end_time": schedule.program_end.isoformat() if schedule.program_end else None,
                        "start_timestamp": schedule.start_timestamp,
                        "stop_timestamp": schedule.stop_timestamp,
                        "duration_minutes": schedule.duration_minutes,
                        "epg_id": schedule.epg_id,
                        "id": schedule.program_id,
                    }

                    download = await build_download_from_program(
                        session,
                        account_id=schedule.account_id,
                        channel_id=schedule.channel_id,
                        channel_name=schedule.channel_name,
                        program=program,
                        custom_filename=schedule.custom_filename,
                        pre_padding_minutes=schedule.pre_padding_minutes,
                        post_padding_minutes=schedule.post_padding_minutes,
                    )

                    download = await download_manager.queue_download(download)
                    schedule.download_id = download.id
                    schedule.status = ScheduledStatus.QUEUED.value
                    schedule.status_message = None
                    schedule.updated_at = datetime.utcnow()
                except Exception as exc:
                    schedule.status = ScheduledStatus.FAILED.value
                    schedule.status_message = str(exc)
                    schedule.updated_at = datetime.utcnow()

            await session.commit()

    def _get_free_space_gb(self, path: str) -> float:
        if not os.path.exists(path):
            os.makedirs(path, exist_ok=True)
        usage = shutil.disk_usage(path)
        return usage.free / (1024 ** 3)


scheduled_manager = ScheduledManager()
