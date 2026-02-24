import asyncio
import json
from collections import deque
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

from config import ensure_config_files


class BackendLogStream:
    def __init__(self, max_entries: int = 2000):
        self._entries = deque(maxlen=max_entries)
        self._connections: set[Any] = set()
        self._lock = asyncio.Lock()
        self._sequence = 0
        self._logs_dir = ensure_config_files() / "logs"
        self._logs_dir.mkdir(parents=True, exist_ok=True)

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

        await self._append_to_file(entry)

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

    def _log_file_for_now(self) -> Path:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self._logs_dir / f"app-events-{day}.jsonl"

    async def _append_to_file(self, entry: dict) -> None:
        try:
            path = self._log_file_for_now()
            serialized = json.dumps(entry, ensure_ascii=True)
            await asyncio.to_thread(self._append_line, path, serialized)
            await asyncio.to_thread(self._prune_old_files)
        except Exception:
            return

    def _append_line(self, path: Path, line: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    def _prune_old_files(self) -> None:
        cutoff_day = (datetime.now(timezone.utc) - timedelta(days=2)).date()
        for file_path in self._logs_dir.glob("app-events-*.jsonl"):
            day = self._extract_day(file_path)
            if day is None:
                continue
            if day < cutoff_day:
                try:
                    file_path.unlink()
                except Exception:
                    continue

    def _extract_day(self, file_path: Path):
        stem = file_path.stem
        prefix = "app-events-"
        if not stem.startswith(prefix):
            return None
        date_text = stem[len(prefix):]
        try:
            return datetime.strptime(date_text, "%Y-%m-%d").date()
        except ValueError:
            return None

    def _read_persisted_entries(self) -> list[dict]:
        entries: list[dict] = []
        for file_path in sorted(self._logs_dir.glob("app-events-*.jsonl")):
            day = self._extract_day(file_path)
            if day is None:
                continue
            for line in file_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                if not line.strip():
                    continue
                try:
                    parsed = json.loads(line)
                except Exception:
                    continue
                if isinstance(parsed, dict):
                    entries.append(parsed)
        return entries

    def _dedupe_entries(self, entries: list[dict]) -> list[dict]:
        by_key: dict[tuple, dict] = {}
        for entry in entries:
            key = (
                entry.get("timestamp"),
                entry.get("source"),
                entry.get("level"),
                entry.get("message"),
                entry.get("download_id"),
                entry.get("account_id"),
            )
            by_key[key] = entry

        merged = list(by_key.values())
        merged.sort(key=lambda e: str(e.get("timestamp") or ""))
        return merged

    def _matches_view(self, entry: dict, view: str) -> bool:
        source_name = str(entry.get("source") or "").lower()
        level_name = str(entry.get("level") or "info").lower()

        if view == "detailed":
            return level_name in {"debug", "info", "warning", "error"}
        if view == "minimal":
            return level_name in {"warning", "error"}
        return source_name != "server" and level_name in {"info", "warning", "error"}

    async def list_entries(
        self,
        limit: int = 300,
        source: Optional[str] = None,
        level: Optional[str] = None,
        view: str = "basic",
    ) -> list[dict]:
        await asyncio.to_thread(self._prune_old_files)

        async with self._lock:
            mem_entries = list(self._entries)

        persisted_entries = await asyncio.to_thread(self._read_persisted_entries)
        entries = self._dedupe_entries([*persisted_entries, *mem_entries])

        view_name = (view or "basic").lower()
        if view_name not in {"detailed", "basic", "minimal"}:
            view_name = "basic"
        entries = [entry for entry in entries if self._matches_view(entry, view_name)]

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
