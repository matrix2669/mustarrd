import asyncio
import logging
from typing import Optional

from services.log_stream import backend_log_stream


class _ServerLogBridgeHandler(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.INFO)
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._active = False

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def emit(self, record: logging.LogRecord) -> None:
        if not self._active:
            return
        if record.name.startswith("uvicorn.access"):
            return
        if record.name.startswith("backend.services.server_log_bridge"):
            return

        loop = self._loop
        if loop is None or loop.is_closed():
            return

        level = record.levelname.lower()
        if level not in {"debug", "info", "warning", "error"}:
            if level in {"critical", "fatal"}:
                level = "error"
            else:
                level = "info"

        message = record.getMessage()
        try:
            loop.call_soon_threadsafe(
                asyncio.create_task,
                backend_log_stream.emit(
                    source="server",
                    message=message,
                    level=level,
                ),
            )
        except Exception:
            return

    def start(self) -> None:
        self._active = True

    def stop(self) -> None:
        self._active = False


_handler: Optional[_ServerLogBridgeHandler] = None
_target_loggers = ("uvicorn", "uvicorn.error", "fastapi")


def start_server_log_bridge(loop: asyncio.AbstractEventLoop) -> None:
    global _handler
    if _handler is not None:
        return

    handler = _ServerLogBridgeHandler()
    handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))
    handler.set_loop(loop)

    for logger_name in _target_loggers:
        logger = logging.getLogger(logger_name)
        logger.addHandler(handler)

    handler.start()
    _handler = handler


def stop_server_log_bridge() -> None:
    global _handler
    if _handler is None:
        return

    _handler.stop()
    for logger_name in _target_loggers:
        logger = logging.getLogger(logger_name)
        try:
            logger.removeHandler(_handler)
        except Exception:
            continue
    _handler = None
