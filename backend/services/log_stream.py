import asyncio
from collections import deque
from datetime import datetime, timezone
from typing import Any, Optional


class BackendLogStream:
    def __init__(self, max_entries: int = 2000):
        self._entries = deque(maxlen=max_entries)
        self._connections: set[Any] = set()
        self._lock = asyncio.Lock()
        self._sequence = 0

    async def register_websocket(self, websocket: Any):
        async with self._lock:
            self._connections.add(websocket)

    async def unregister_websocket(self, websocket: Any):
        async with self._lock:
            self._connections.discard(websocket)

    async def emit(
        self,
        source: str,
        message: str,
        level: str = "info",
        download_id: Optional[int] = None,
        account_id: Optional[int] = None,
        account_name: Optional[str] = None,
    ) -> dict:
        async with self._lock:
            self._sequence += 1
            entry = {
                "id": self._sequence,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source": source,
                "level": level,
                "message": message,
            }
            if download_id is not None:
                entry["download_id"] = download_id
            if account_id is not None:
                entry["account_id"] = account_id
            if account_name is not None:
                entry["account_name"] = account_name

            self._entries.append(entry)
            connections = list(self._connections)

        dead_connections = []
        payload = {"type": "backend_log", "entry": entry}
        for ws in connections:
            try:
                await ws.send_json(payload)
            except Exception:
                dead_connections.append(ws)

        if dead_connections:
            async with self._lock:
                for ws in dead_connections:
                    self._connections.discard(ws)

        return entry

    async def list_entries(
        self,
        limit: int = 300,
        source: Optional[str] = None,
        level: Optional[str] = None,
    ) -> list[dict]:
        async with self._lock:
            entries = list(self._entries)

        if source:
            source_lower = source.lower()
            entries = [entry for entry in entries if str(entry.get("source", "")).lower() == source_lower]
        if level:
            level_lower = level.lower()
            entries = [entry for entry in entries if str(entry.get("level", "")).lower() == level_lower]

        if limit <= 0:
            return []

        return entries[-limit:]


backend_log_stream = BackendLogStream()
