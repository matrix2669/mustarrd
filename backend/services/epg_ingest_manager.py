import asyncio
import gzip
import io
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, Optional

from sqlalchemy import delete, insert, select

from config import settings as app_settings
from database import async_session_maker
from models import EPGProgram, XtreamAccount
from services.xtream_client import XtreamClient
from services.epg_service import epg_service


class EPGIngestManager:
    def __init__(self):
        self._running = False
        self._interval = max(1, int(app_settings.epg_refresh_interval_hours)) * 3600

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

    async def _refresh_all_accounts(self):
        async with async_session_maker() as session:
            result = await session.execute(
                select(XtreamAccount).where(XtreamAccount.is_active == True)  # noqa: E712
            )
            accounts = result.scalars().all()

        for account in accounts:
            try:
                await self._refresh_account(account)
            except Exception as exc:
                print(f"Error refreshing XMLTV for account {account.id}: {exc}")

    async def _refresh_account(self, account: XtreamAccount):
        client = XtreamClient(account.server_url, account.username, account.password)
        try:
            channels = await client.get_live_streams()
            catchup_channels = [
                ch for ch in channels
                if int(ch.get("tv_archive", 0) or 0) == 1
            ]
            channel_maps = self._build_channel_maps(catchup_channels)

            raw_xmltv = await client.get_xmltv()
        finally:
            await client.close()

        if not raw_xmltv:
            return

        xmltv_bytes = self._maybe_decompress(raw_xmltv)
        now_utc = datetime.now(timezone.utc)
        cutoff = now_utc - timedelta(days=account.catchup_days)

        program_iter = self._iter_programs(
            xmltv_bytes,
            channel_maps,
            cutoff,
        )

        async with async_session_maker() as session:
            async with session.begin():
                await session.execute(
                    delete(EPGProgram).where(EPGProgram.account_id == account.id)
                )

                batch: list[dict] = []
                for program in program_iter:
                    program["account_id"] = account.id
                    batch.append(program)
                    if len(batch) >= 1000:
                        await session.execute(insert(EPGProgram), batch)
                        batch = []

                if batch:
                    await session.execute(insert(EPGProgram), batch)

        epg_service.clear_cache()

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


epg_ingest_manager = EPGIngestManager()
