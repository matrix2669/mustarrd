"""One seam for running external tools (ffmpeg, ffprobe, comskip).

The post-processor used to call ``subprocess.run`` and
``asyncio.create_subprocess_exec`` inline at many sites, each repeating the
spawn / capture / terminate-on-cancel dance. That made the work impossible to
test without spawning real binaries.

``ProcessRunner`` is the real adapter; ``FakeProcessRunner`` is the test
adapter. Callers depend on the small interface here, not on subprocess. Two
shapes:

- ``run_sync``    — blocking capability probe; returns text like
  ``subprocess.run`` and raises the same exceptions.
- ``run_capture`` — async spawn, capture stdout/stderr, terminate the child on
  cancellation or timeout, and report a timeout instead of hanging.
"""

import asyncio
import subprocess
from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class CommandResult:
    """Outcome of an async captured command.

    ``returncode`` is ``None`` when the command was killed for timing out;
    check ``timed_out`` to distinguish that from a process that exited.
    """

    returncode: Optional[int]
    stdout: bytes = b""
    stderr: bytes = b""
    timed_out: bool = False

    @property
    def stdout_text(self) -> str:
        return self.stdout.decode(errors="ignore")

    @property
    def stderr_text(self) -> str:
        return self.stderr.decode(errors="ignore")


async def terminate_process(process: "asyncio.subprocess.Process") -> None:
    """Terminate a child, escalating to kill if it ignores SIGTERM."""
    if process.returncode is not None:
        return
    try:
        process.terminate()
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(process.wait(), timeout=5)
    except asyncio.TimeoutError:
        try:
            process.kill()
        except ProcessLookupError:
            return
        await process.wait()


class ProcessRunner:
    """Real adapter: runs external commands via subprocess."""

    def run_sync(
        self, cmd: List[str], timeout: Optional[float] = None
    ) -> subprocess.CompletedProcess:
        """Blocking probe. Raises FileNotFoundError / TimeoutExpired like
        ``subprocess.run`` so callers can map them to messages."""
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

    async def run_capture(
        self,
        cmd: List[str],
        env: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> CommandResult:
        """Spawn, capture all output, and return a CommandResult.

        Terminates the child on timeout (returns ``timed_out=True``) or on
        cancellation (re-raises ``CancelledError``). Raises ``FileNotFoundError``
        if the executable is missing.
        """
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            await terminate_process(process)
            return CommandResult(returncode=None, timed_out=True)
        except asyncio.CancelledError:
            await terminate_process(process)
            raise
        return CommandResult(
            returncode=process.returncode, stdout=stdout, stderr=stderr
        )


class FakeProcessRunner:
    """Test adapter: returns canned results in order and records calls.

    Queue results before the code under test runs. Each call pops the next
    queued item; queue a ``BaseException`` to make a call raise.
    """

    def __init__(self) -> None:
        self.sync_results: List[object] = []
        self.capture_results: List[object] = []
        self.calls: List[tuple] = []

    # --- queueing helpers -------------------------------------------------
    def queue_sync(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.sync_results.append(
            subprocess.CompletedProcess([], returncode, stdout, stderr)
        )

    def queue_sync_error(self, exc: BaseException) -> None:
        self.sync_results.append(exc)

    def queue_capture(
        self,
        returncode: Optional[int] = 0,
        stdout: bytes = b"",
        stderr: bytes = b"",
        timed_out: bool = False,
    ) -> None:
        self.capture_results.append(
            CommandResult(returncode, stdout, stderr, timed_out)
        )

    def queue_capture_error(self, exc: BaseException) -> None:
        self.capture_results.append(exc)

    # --- interface --------------------------------------------------------
    def run_sync(
        self, cmd: List[str], timeout: Optional[float] = None
    ) -> subprocess.CompletedProcess:
        self.calls.append(("sync", list(cmd)))
        item = self.sync_results.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    async def run_capture(
        self,
        cmd: List[str],
        env: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> CommandResult:
        self.calls.append(("capture", list(cmd)))
        item = self.capture_results.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item
