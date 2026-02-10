import asyncio
import base64
import gzip
import io
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, Optional

from sqlalchemy import delete, insert, select, func

from config import settings as app_settings
from database import async_session_maker
from models import EPGProgram, XtreamAccount
from services.xtream_client import XtreamClient
from services.epg_service import epg_service


class EPGIngestManager:
    def __init__(self):
        self._running = False
        self._interval = max(1, int(app_settings.epg_refresh_interval_hours)) * 3600
        self._status = {
            "running": False,
            "account_id": None,
            "account_name": None,
            "processed_programs": 0,
            "total_programs": None,
            "started_at": None,
            "last_completed_at": None,
            "last_error": None,
        }

    async def process_queue(self):
        self._running = True
        while self._running:
            try:
                await self._refresh_all_accounts()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                print(f"Error refreshing XMLTV: {exc}")
            await asyncio.sleep(self._interval)

    def get_status(self) -> dict:
        status = dict(self._status)
        for key in ("started_at", "last_completed_at"):
            if status.get(key):
                status[key] = status[key].isoformat()
        return status

    async def _refresh_all_accounts(self):
        async with async_session_maker() as session:
            result = await session.execute(
                select(XtreamAccount).where(XtreamAccount.is_active == True)  # noqa: E712
            )
            accounts = result.scalars().all()

        self._status.update({
            "running": True,
            "account_id": None,
            "account_name": None,
            "processed_programs": 0,
            "total_programs": None,
            "started_at": datetime.now(timezone.utc),
            "last_error": None,
        })

        for account in accounts:
            try:
                await self._refresh_account(account)
            except Exception as exc:
                self._status.update({
                    "last_error": str(exc),
                })
                print(f"Error refreshing XMLTV for account {account.id}: {exc}")

        self._status.update({
            "running": False,
            "last_completed_at": datetime.now(timezone.utc),
        })

    async def _refresh_account(self, account: XtreamAccount):
        self._status.update({
            "running": True,
            "account_id": account.id,
            "account_name": account.name,
            "processed_programs": 0,
            "total_programs": None,
            "started_at": datetime.now(timezone.utc),
            "last_error": None,
        })
        processed = 0
        client = XtreamClient(account.server_url, account.username, account.password)
        insert_stmt = insert(EPGProgram).prefix_with("OR IGNORE")
        try:
            channels = await client.get_live_streams()
            catchup_channels = [
                ch for ch in channels
                if int(ch.get("tv_archive", 0) or 0) == 1
            ]
            channel_maps = self._build_channel_maps(catchup_channels)

            raw_xmltv = await client.get_xmltv()
            xmltv_bytes = self._maybe_decompress(raw_xmltv) if raw_xmltv else b""
            total_programs = xmltv_bytes.count(b"<programme") if xmltv_bytes else 0
            self._status["total_programs"] = total_programs if total_programs > 0 else None

            now_utc = datetime.now(timezone.utc)
            cutoff = now_utc - timedelta(days=account.catchup_days)
            earliest_start_in_range: Optional[datetime] = None

            async with async_session_maker() as session:
                async with session.begin():
                    await session.execute(
                        delete(EPGProgram).where(
                            EPGProgram.account_id == account.id,
                            EPGProgram.end_time < cutoff,
                        )
                    )

                earliest_result = await session.execute(
                    select(func.min(EPGProgram.start_time)).where(
                        EPGProgram.account_id == account.id
                    )
                )
            earliest_start_in_range = self._ensure_aware(earliest_result.scalar_one_or_none())

                if xmltv_bytes:
                    program_iter = self._iter_programs(
                        xmltv_bytes,
                        channel_maps,
                        cutoff,
                    )

                    batch: list[dict] = []
                    for program in program_iter:
                        start_time = self._ensure_aware(program.get("start_time"))
                        if start_time:
                            if earliest_start_in_range is None or start_time < earliest_start_in_range:
                                earliest_start_in_range = start_time
                        program["account_id"] = account.id
                        batch.append(program)
                        processed += 1
                        if processed % 500 == 0:
                            self._status["processed_programs"] = processed
                        if len(batch) >= 1000:
                            async with session.begin():
                                await session.execute(insert_stmt, batch)
                            batch = []

                    if batch:
                        async with session.begin():
                            await session.execute(insert_stmt, batch)

            backfill_end: Optional[datetime] = None
            if earliest_start_in_range is None:
                backfill_end = now_utc
            elif earliest_start_in_range > cutoff:
                backfill_end = earliest_start_in_range

            if backfill_end is not None and catchup_channels:
                backfill_end = self._ensure_aware(backfill_end)
                self._status["total_programs"] = None
                processed = await self._backfill_from_api(
                    client,
                    catchup_channels,
                    cutoff,
                    backfill_end,
                    processed,
                    account.id,
                    insert_stmt,
                )
            elif not xmltv_bytes and earliest_start_in_range is None:
                self._status["last_error"] = "No XMLTV data returned by provider."

        finally:
            await client.close()

        epg_service.clear_cache()
        self._status.update({
            "processed_programs": processed,
            "last_completed_at": datetime.now(timezone.utc),
        })

    def _build_channel_maps(self, channels: list[dict]) -> dict:
        stream_by_xmltv_id: Dict[str, str] = {}
        stream_by_name: Dict[str, str] = {}
        stream_info: Dict[str, dict] = {}

        for ch in channels:
            stream_id = str(ch.get("stream_id"))
            name = (ch.get("name") or "").strip()
            stream_info[stream_id] = {
                "name": name or stream_id,
                "has_archive": int(ch.get("tv_archive", 0) or 0) == 1,
            }

            xmltv_id = self._extract_xmltv_id(ch)
            if xmltv_id:
                stream_by_xmltv_id[str(xmltv_id)] = stream_id

            if name:
                stream_by_name[self._normalize_name(name)] = stream_id

        return {
            "stream_by_xmltv_id": stream_by_xmltv_id,
            "stream_by_name": stream_by_name,
            "stream_info": stream_info,
        }

    def _iter_programs(
        self,
        xmltv_bytes: bytes,
        channel_maps: dict,
        cutoff: datetime,
    ) -> Iterable[dict]:
        stream_by_xmltv_id = channel_maps["stream_by_xmltv_id"]
        stream_by_name = channel_maps["stream_by_name"]
        stream_info = channel_maps["stream_info"]
        xmltv_to_stream: Dict[str, str] = dict(stream_by_xmltv_id)

        for _, elem in ET.iterparse(io.BytesIO(xmltv_bytes), events=("end",)):
            if elem.tag == "channel":
                xmltv_id = elem.get("id")
                display_name = self._extract_text(elem, "display-name")
                if xmltv_id and xmltv_id not in xmltv_to_stream:
                    if xmltv_id in stream_info:
                        xmltv_to_stream[xmltv_id] = xmltv_id
                    elif display_name:
                        name_key = self._normalize_name(display_name)
                        stream_id = stream_by_name.get(name_key)
                        if stream_id:
                            xmltv_to_stream[xmltv_id] = stream_id
                elem.clear()
                continue

            if elem.tag != "programme":
                continue

            xmltv_id = elem.get("channel")
            if not xmltv_id:
                elem.clear()
                continue

            stream_id = xmltv_to_stream.get(xmltv_id)
            if not stream_id or stream_id not in stream_info:
                elem.clear()
                continue

            start_raw = elem.get("start")
            stop_raw = elem.get("stop")
            start_dt = self._parse_xmltv_time(start_raw)
            end_dt = self._parse_xmltv_time(stop_raw)
            if not start_dt or not end_dt:
                elem.clear()
                continue

            start_utc = start_dt.astimezone(timezone.utc)
            end_utc = end_dt.astimezone(timezone.utc)
            if end_utc < cutoff:
                elem.clear()
                continue

            duration_minutes = int((end_utc - start_utc).total_seconds() / 60)
            if duration_minutes <= 0:
                elem.clear()
                continue

            title = self._extract_text(elem, "title") or "Unknown"
            description = self._extract_text(elem, "desc")
            category = self._extract_text(elem, "category")

            start_ts = int(start_utc.timestamp())
            stop_ts = int(end_utc.timestamp())
            epg_id = f"{stream_id}:{start_ts}:{stop_ts}"

            info = stream_info[stream_id]
            yield {
                "channel_id": stream_id,
                "channel_name": info["name"],
                "xmltv_id": xmltv_id,
                "epg_id": epg_id,
                "title": title,
                "description": description,
                "category": category,
                "start_time": start_utc,
                "end_time": end_utc,
                "start_timestamp": start_ts,
                "stop_timestamp": stop_ts,
                "duration_minutes": duration_minutes,
                "has_archive": info["has_archive"],
            }

            elem.clear()

    def _maybe_decompress(self, data: bytes) -> bytes:
        if data[:2] == b"\x1f\x8b":
            return gzip.decompress(data)
        return data

    def _ensure_aware(self, value: Optional[datetime]) -> Optional[datetime]:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    def _parse_xmltv_time(self, value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        value = value.strip()
        if len(value) >= 14:
            date_part = value[:14]
            tz_part = value[14:].strip()
            try:
                dt = datetime.strptime(date_part, "%Y%m%d%H%M%S")
            except ValueError:
                return None
            if tz_part:
                try:
                    if tz_part[0] not in "+-":
                        tz_part = tz_part.replace(" ", "")
                    if tz_part.upper() == "Z":
                        return dt.replace(tzinfo=timezone.utc)
                    if len(tz_part) == 6 and tz_part[3] == ":":
                        tz_part = tz_part.replace(":", "")
                    offset = datetime.strptime(tz_part, "%z").tzinfo
                    return dt.replace(tzinfo=offset)
                except ValueError:
                    return dt.replace(tzinfo=timezone.utc)
            return dt.replace(tzinfo=timezone.utc)
        return None

    def _extract_text(self, elem: ET.Element, tag: str) -> Optional[str]:
        child = elem.find(tag)
        if child is not None and child.text:
            return child.text.strip()
        return None

    def _extract_xmltv_id(self, channel: dict) -> Optional[str]:
        for key in ("epg_channel_id", "tvg_id", "tvgid", "tvg_name", "tvg-id"):
            value = channel.get(key)
            if value:
                return str(value).strip()
        return None

    def _normalize_name(self, name: str) -> str:
        return " ".join(name.lower().split())

    def _decode_base64_text(self, value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        try:
            return base64.b64decode(value).decode("utf-8")
        except Exception:
            return value

    async def _backfill_from_api(
        self,
        client: XtreamClient,
        channels: list[dict],
        cutoff: datetime,
        backfill_end: datetime,
        processed: int,
        account_id: int,
        insert_stmt,
    ) -> int:
        async with async_session_maker() as session:
            batch: list[dict] = []

            async def flush_batch():
                nonlocal batch
                if not batch:
                    return
                async with session.begin():
                    await session.execute(insert_stmt, batch)
                batch = []

            for channel in channels:
                stream_id = str(channel.get("stream_id"))
                if not stream_id:
                    continue
                channel_name = (channel.get("name") or stream_id).strip()
                xmltv_id = self._extract_xmltv_id(channel)

                try:
                    epg_entries = await client.get_epg(stream_id)
                except Exception as exc:
                    self._status["last_error"] = f"EPG fetch failed for channel {stream_id}: {exc}"
                    continue

                for entry in epg_entries:
                    start_ts = entry.get("start_timestamp")
                    stop_ts = entry.get("stop_timestamp")
                    if not start_ts or not stop_ts:
                        continue
                    try:
                        start_ts = int(start_ts)
                        stop_ts = int(stop_ts)
                    except (TypeError, ValueError):
                        continue

                    start_utc = datetime.fromtimestamp(start_ts, tz=timezone.utc)
                    end_utc = datetime.fromtimestamp(stop_ts, tz=timezone.utc)
                    if end_utc < cutoff or end_utc >= backfill_end:
                        continue

                    duration_minutes = int((end_utc - start_utc).total_seconds() / 60)
                    if duration_minutes <= 0:
                        continue

                    title = self._decode_base64_text(entry.get("title")) or "Unknown"
                    description = self._decode_base64_text(entry.get("description"))
                    category = entry.get("category")
                    epg_id = entry.get("epg_id") or f"{stream_id}:{start_ts}:{stop_ts}"
                    has_archive = entry.get("has_archive", 0) == 1

                    batch.append({
                        "account_id": account_id,
                        "channel_id": stream_id,
                        "channel_name": channel_name or stream_id,
                        "xmltv_id": xmltv_id,
                        "epg_id": str(epg_id),
                        "title": title,
                        "description": description,
                        "category": category,
                        "start_time": start_utc,
                        "end_time": end_utc,
                        "start_timestamp": start_ts,
                        "stop_timestamp": stop_ts,
                        "duration_minutes": duration_minutes,
                        "has_archive": has_archive,
                    })
                    processed += 1
                    if processed % 500 == 0:
                        self._status["processed_programs"] = processed
                    if len(batch) >= 1000:
                        await flush_batch()

            await flush_batch()

        return processed


epg_ingest_manager = EPGIngestManager()
