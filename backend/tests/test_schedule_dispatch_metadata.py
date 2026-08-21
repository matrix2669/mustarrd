import sys
import unittest
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from models import AppSettings, EPGProgram, ScheduledRecording, ScheduledStatus
from services.file_namer import FileNamer
from services.scheduled_manager import ScheduledManager

NOW = datetime.now(timezone.utc)
END = NOW - timedelta(minutes=5)
START = END - timedelta(hours=1)


def _make_ready_schedule() -> ScheduledRecording:
    """A schedule whose airing has finished, so the next tick dispatches it."""
    return ScheduledRecording(
        account_id=1,
        channel_id="101",
        channel_name="Test Channel",
        channel_category_name="Entertainment",
        program_title="The Price Is Right",
        program_description="Contestants guess the prices of items.",
        program_start=START.replace(tzinfo=None),
        program_end=END.replace(tzinfo=None),
        start_timestamp=int(START.timestamp()),
        stop_timestamp=int(END.timestamp()),
        duration_minutes=60,
        status=ScheduledStatus.SCHEDULED.value,
    )


def _make_stored_program(**overrides) -> EPGProgram:
    values = {
        "account_id": 1,
        "channel_id": "101",
        "title": "The Price Is Right",
        "start_timestamp": int(START.timestamp()),
        "stop_timestamp": int(END.timestamp()),
        "season_number": 54,
        "episode_number": 173,
    }
    values.update(overrides)
    return EPGProgram(**values)


def _make_session_maker(schedule, stored_programs):
    """A session that answers each query by the entity it selects."""
    settings_obj = AppSettings()
    settings_obj.download_folder = "/tmp/downloads"
    settings_obj.min_free_space_gb = 1

    def _result(scalar_one=None, scalars=()):
        result = MagicMock()
        result.scalar_one_or_none.return_value = scalar_one
        result.scalars.return_value.all.return_value = list(scalars)
        return result

    async def execute(stmt):
        entity = stmt.column_descriptions[0]["entity"]
        if entity is ScheduledRecording:
            return _result(scalars=[schedule])
        if entity is EPGProgram:
            return _result(scalars=stored_programs)
        return _result(scalar_one=settings_obj)

    session = AsyncMock()
    session.execute = execute
    session.commit = AsyncMock()

    @asynccontextmanager
    async def ctx():
        yield session

    return ctx


class ScheduleDispatchMetadataTests(unittest.IsolatedAsyncioTestCase):
    """A scheduled recording is named from the guide, not just its own snapshot.

    The schedule row saves the title, description and times of the airing and
    nothing else, so without this the season and episode the guide published
    are gone by the time the recording is named.
    """

    async def _dispatch(self, schedule, stored_programs) -> dict:
        captured = {}

        async def fake_build(session, **kwargs):
            captured["program"] = kwargs.get("program", {})
            download = MagicMock()
            download.id = 99
            return download

        fake_dm = MagicMock()
        fake_dm.queue_download = AsyncMock(side_effect=lambda dl, session=None: dl)
        fake_dm.enqueue_persisted = AsyncMock(side_effect=lambda dl: dl)

        manager = ScheduledManager()

        with (
            patch(
                "services.scheduled_manager.async_session_maker",
                _make_session_maker(schedule, stored_programs),
            ),
            patch("services.scheduled_manager.build_download_from_program", new=fake_build),
            patch("services.scheduled_manager.download_manager", fake_dm),
            patch.object(manager, "_get_free_space_gb", return_value=100.0),
            patch.object(manager, "_get_catchup_window_days", new=AsyncMock(return_value=7)),
        ):
            await manager._queue_ready_recordings()

        return captured.get("program", {})

    async def test_recording_named_with_stored_season_and_episode(self):
        program = await self._dispatch(_make_ready_schedule(), [_make_stored_program()])

        self.assertEqual(
            FileNamer().generate_filename(program, {"name": "Test Channel"}, "tv_show"),
            "The Price Is Right - S54E173.ts",
        )

    async def test_no_matching_stored_program_names_as_before(self):
        # Same channel, different airing: nothing is borrowed.
        stored = _make_stored_program(start_timestamp=int(START.timestamp()) - 3600)
        program = await self._dispatch(_make_ready_schedule(), [stored])

        self.assertIsNone(program.get("season_number"))
        self.assertEqual(
            FileNamer().generate_filename(program, {"name": "Test Channel"}, "tv_show"),
            f"The Price Is Right - {START.strftime('%Y-%m-%d')}.ts",
        )

    async def test_snapshot_title_and_times_are_not_overwritten(self):
        stored = _make_stored_program(title="A Stale Title")
        program = await self._dispatch(_make_ready_schedule(), [stored])

        self.assertEqual(program["title"], "The Price Is Right")
        self.assertEqual(program["start_timestamp"], int(START.timestamp()))
        self.assertEqual(program["stop_timestamp"], int(END.timestamp()))


if __name__ == "__main__":
    unittest.main()
