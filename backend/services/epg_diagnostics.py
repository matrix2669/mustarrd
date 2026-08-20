import io
import random
from datetime import datetime, timezone
from typing import Any, Iterable, Optional
from xml.etree.ElementTree import tostring

from defusedxml import ElementTree as ET
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import AppSettings, EPGProgram, XtreamAccount
from services.account_credentials import resolve_account_password
from services.epg_ingest_manager import _sanitize_html_entities, epg_ingest_manager
from services.epg_service import epg_service
from services.xtream_client import XtreamClient


_SENSITIVE_KEY_NAMES = {
    "password",
    "password_encrypted",
    "username",
    "server_url",
    "token",
    "secret",
    "authorization",
    "auth",
}

_PROVIDER_CHANNEL_FIELDS = (
    "stream_id",
    "num",
    "name",
    "category_id",
    "epg_channel_id",
    "tvg_id",
    "tvgid",
    "tvg_name",
    "tvg-id",
    "tv_archive",
    "tv_archive_duration",
    "stream_type",
    "added",
    "is_adult",
    "custom_sid",
)


def _local_tag(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def _redact_text(value: str, secrets: Iterable[str]) -> str:
    redacted = value
    for secret in secrets:
        if secret:
            redacted = redacted.replace(str(secret), "[REDACTED]")
    return redacted


def _scrub_value(value: Any, secrets: Iterable[str]) -> Any:
    """Recursively remove credentials while retaining unknown diagnostic fields."""
    if isinstance(value, dict):
        scrubbed = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text.lower() in _SENSITIVE_KEY_NAMES:
                scrubbed[key_text] = "[REDACTED]"
            else:
                scrubbed[key_text] = _scrub_value(item, secrets)
        return scrubbed
    if isinstance(value, (list, tuple)):
        return [_scrub_value(item, secrets) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str):
        return _redact_text(value, secrets)
    return value


def _select_evenly(items: list[Any], limit: int) -> list[Any]:
    """Select stable samples spread across an ordered source list."""
    if limit <= 0 or not items:
        return []
    if len(items) <= limit:
        return list(items)
    # Pick the midpoint of each equally-sized stratum. Since limit <= len(items),
    # these indexes are unique and cover the full list rather than only its head.
    return [items[int((index + 0.5) * len(items) / limit)] for index in range(limit)]


class _Reservoir:
    """Bounded deterministic reservoir sample for streamed XMLTV programmes."""

    def __init__(self, limit: int, seed: str):
        self.limit = max(0, int(limit))
        self._rng = random.Random(seed)
        self.seen = 0
        self.items: list[Any] = []

    def add(self, item: Any) -> None:
        self.seen += 1
        if self.limit <= 0:
            return
        if len(self.items) < self.limit:
            self.items.append(item)
            return
        replace_index = self._rng.randrange(self.seen)
        if replace_index < self.limit:
            self.items[replace_index] = item


def _xmltv_program_snapshot(elem, secrets: Iterable[str]) -> dict:
    """Capture a programme without assuming which Gracenote/XMLTV fields matter."""
    children: dict[str, list[dict]] = {}
    for child in elem:
        tag = _local_tag(child.tag)
        text = "".join(child.itertext()).strip() or None
        children.setdefault(tag, []).append(
            {
                "text": _scrub_value(text, secrets),
                "attributes": _scrub_value(dict(child.attrib), secrets),
            }
        )

    raw_xml = tostring(elem, encoding="unicode")
    # A pathological description should not make one sampled record enormous.
    if len(raw_xml) > 32768:
        raw_xml = raw_xml[:32768] + "\n...[truncated]"

    return {
        "source": "xmltv_raw",
        "attributes": _scrub_value(dict(elem.attrib), secrets),
        "children": children,
        "raw_xml": _redact_text(raw_xml, secrets),
    }


def _provider_channel_snapshot(
    channel: dict,
    category_names: dict[str, str],
    secrets: Iterable[str],
) -> dict:
    snapshot = {
        key: _scrub_value(channel.get(key), secrets)
        for key in _PROVIDER_CHANNEL_FIELDS
        if key in channel
    }
    category_id = str(channel.get("category_id") or "")
    if category_id and category_id in category_names:
        snapshot["category_name"] = category_names[category_id]
    snapshot["extra_field_names"] = sorted(
        str(key) for key in channel.keys() if key not in _PROVIDER_CHANNEL_FIELDS
    )
    return snapshot


def _stored_program_snapshot(row: EPGProgram) -> dict:
    return {
        "id": row.id,
        "account_id": row.account_id,
        "channel_id": row.channel_id,
        "channel_name": row.channel_name,
        "xmltv_id": row.xmltv_id,
        "epg_id": row.epg_id,
        "title": row.title,
        "description": row.description,
        "category": row.category,
        "start_time": row.start_time.isoformat() if row.start_time else None,
        "end_time": row.end_time.isoformat() if row.end_time else None,
        "start_timestamp": row.start_timestamp,
        "stop_timestamp": row.stop_timestamp,
        "provider_start": row.provider_start,
        "provider_stop": row.provider_stop,
        "duration_minutes": row.duration_minutes,
        "has_archive": row.has_archive,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _classification_snapshot(program: dict, channel_name: str) -> dict:
    channel_context = {
        "name": channel_name,
        "stream_id": program.get("channel_id"),
        # This mirrors download_builder: the programme category is used as the
        # classifier's channel-category context.
        "category_name": program.get("category", "") or "",
    }
    result = epg_service.detect_program_type(program, channel_context)
    return {
        "result": result,
        "inputs": {
            "title": program.get("title"),
            "description": program.get("description"),
            "category": program.get("category"),
            "channel_name": channel_name,
        },
    }


def _sample_xmltv(
    xmltv_bytes: bytes,
    catchup_channels: list[dict],
    selected_stream_ids: set[str],
    account_id: int,
    programs_per_channel: int,
    overall_limit: int,
    secrets: Iterable[str],
) -> dict:
    decompressed = epg_ingest_manager._maybe_decompress(xmltv_bytes) if xmltv_bytes else b""
    result: dict[str, Any] = {
        "source": "xmltv_raw",
        "downloaded_bytes": len(decompressed),
        "parse_ok": True,
        "programme_count_seen": 0,
        "overall_samples": [],
        "by_selected_channel": {},
    }
    if not decompressed:
        return result

    channel_maps = epg_ingest_manager._build_channel_maps(catchup_channels)
    xmltv_to_stream, scan_ok = epg_ingest_manager._scan_channel_map(decompressed, channel_maps)
    result["parse_ok"] = scan_ok

    overall = _Reservoir(overall_limit, f"{account_id}:xmltv:overall")
    per_channel = {
        stream_id: _Reservoir(
            programs_per_channel,
            f"{account_id}:xmltv:{stream_id}",
        )
        for stream_id in selected_stream_ids
    }

    try:
        stream = io.BytesIO(_sanitize_html_entities(decompressed))
        for _, elem in ET.iterparse(stream, events=("end",)):
            if _local_tag(elem.tag) != "programme":
                continue

            xmltv_id = (elem.get("channel") or "").lower() or None
            mapped_stream_ids = [
                str(value)
                for value in epg_ingest_manager._as_stream_ids(
                    xmltv_to_stream.get(xmltv_id) if xmltv_id else None
                )
            ]
            snapshot = _xmltv_program_snapshot(elem, secrets)
            snapshot["mapped_stream_ids"] = mapped_stream_ids
            overall.add(snapshot)
            result["programme_count_seen"] += 1

            for stream_id in mapped_stream_ids:
                reservoir = per_channel.get(stream_id)
                if reservoir is not None:
                    reservoir.add(snapshot)

            elem.clear()
    except ET.ParseError as exc:
        result["parse_ok"] = False
        result["parse_error"] = str(exc)

    result["overall_samples"] = overall.items
    result["by_selected_channel"] = {
        stream_id: {
            "programme_count_seen": reservoir.seen,
            "samples": reservoir.items,
        }
        for stream_id, reservoir in per_channel.items()
    }
    return result


async def _database_channel_inventory(
    session: AsyncSession,
    account_id: int,
) -> list[dict]:
    result = await session.execute(
        select(EPGProgram.channel_id, EPGProgram.channel_name)
        .where(EPGProgram.account_id == account_id)
        .group_by(EPGProgram.channel_id, EPGProgram.channel_name)
        .order_by(EPGProgram.channel_name.asc())
    )
    return [
        {"stream_id": str(channel_id), "name": channel_name, "inventory_source": "database"}
        for channel_id, channel_name in result.all()
    ]


async def _sample_database_and_final(
    session: AsyncSession,
    account: XtreamAccount,
    selected_channels: list[dict],
    programs_per_channel: int,
    global_offset_minutes: int,
) -> tuple[dict, dict]:
    total_result = await session.execute(
        select(func.count(EPGProgram.id)).where(EPGProgram.account_id == account.id)
    )
    total_programs = int(total_result.scalar_one() or 0)

    database_source = {
        "source": "sqlite_epg_programs",
        "total_programs": total_programs,
        "by_selected_channel": {},
    }
    final_source = {
        "source": "mustarrd_serialized_and_classified",
        "by_selected_channel": {},
    }

    scan_limit = max(50, programs_per_channel * 25)
    for channel in selected_channels:
        stream_id = str(channel.get("stream_id") or "")
        if not stream_id:
            continue
        row_result = await session.execute(
            select(EPGProgram)
            .where(
                EPGProgram.account_id == account.id,
                EPGProgram.channel_id == stream_id,
            )
            .order_by(EPGProgram.start_time.desc())
            .limit(scan_limit)
        )
        rows = row_result.scalars().all()
        sampled_rows = _select_evenly(rows, programs_per_channel)

        database_source["by_selected_channel"][stream_id] = {
            "channel_name": channel.get("name"),
            "rows_scanned": len(rows),
            "samples": [_stored_program_snapshot(row) for row in sampled_rows],
        }

        final_samples = []
        for row in sampled_rows:
            serialized = epg_service.serialize_program(
                row,
                account,
                global_offset_minutes,
            )
            final_samples.append(
                {
                    "epg_id": row.epg_id,
                    "serialized_program": serialized,
                    "classification": _classification_snapshot(
                        serialized,
                        row.channel_name,
                    ),
                }
            )
        final_source["by_selected_channel"][stream_id] = {
            "channel_name": channel.get("name"),
            "samples": final_samples,
        }

    return database_source, final_source


async def _sample_live_api(
    client: Optional[XtreamClient],
    account: XtreamAccount,
    selected_channels: list[dict],
    programs_per_channel: int,
    global_offset_minutes: int,
    secrets: Iterable[str],
) -> dict:
    source = {
        "source": "xtream_live_epg_api",
        "by_selected_channel": {},
    }
    if client is None:
        source["error"] = "Provider client unavailable"
        return source

    for channel in selected_channels:
        stream_id = str(channel.get("stream_id") or "")
        if not stream_id:
            continue
        channel_name = str(channel.get("name") or stream_id)
        channel_result = {
            "channel_name": channel_name,
            "entries_returned": 0,
            "samples": [],
        }
        try:
            entries = await client.get_epg(stream_id)
            channel_result["entries_returned"] = len(entries)
            sampled_entries = _select_evenly(entries, programs_per_channel)
            for entry in sampled_entries:
                processed = epg_service._process_epg_entry(
                    entry,
                    account,
                    fallback_channel_id=stream_id,
                    has_archive_fallback=True,
                    global_offset_minutes=global_offset_minutes,
                )
                channel_result["samples"].append(
                    {
                        "raw_entry": _scrub_value(entry, secrets),
                        "raw_field_names": sorted(str(key) for key in entry.keys()),
                        "processed_by_mustarrd": processed,
                        "classification": _classification_snapshot(
                            processed,
                            channel_name,
                        ),
                    }
                )
        except Exception as exc:
            channel_result["error"] = str(exc)[:500]
        source["by_selected_channel"][stream_id] = channel_result
    return source


async def export_epg_classification_diagnostics(
    session: AsyncSession,
    account_id: Optional[int] = None,
    channels_per_account: int = 6,
    programs_per_channel: int = 4,
    xmltv_overall_samples: int = 20,
) -> dict:
    """Export bounded samples from every EPG path used by Mustarrd.

    The export is intentionally read-only. It does not change EPG rows or cache
    state, and it never emits account connection details or credentials.
    """
    query = select(XtreamAccount)
    if account_id is not None:
        query = query.where(XtreamAccount.id == account_id)
    else:
        query = query.where(XtreamAccount.is_active == True)  # noqa: E712
    query = query.order_by(XtreamAccount.id.asc())
    account_result = await session.execute(query)
    accounts = account_result.scalars().all()

    settings_result = await session.execute(select(AppSettings))
    db_settings = settings_result.scalar_one_or_none()
    global_offset_minutes = int(getattr(db_settings, "epg_offset_minutes", 0) or 0)

    export = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "EPG programme classification diagnostics",
        "sampling": {
            "channels_per_account": channels_per_account,
            "programs_per_channel": programs_per_channel,
            "xmltv_overall_samples": xmltv_overall_samples,
            "strategy": (
                "Each active account is sampled independently. Provider/DB channel "
                "inventories are spread across the source list; XMLTV uses bounded "
                "reservoir samples across the complete document and separately for "
                "each selected channel. Live API and SQLite samples are collected "
                "independently for those selected channels."
            ),
        },
        "accounts": [],
    }

    for account in accounts:
        account_export: dict[str, Any] = {
            "account": {
                "id": account.id,
                "name": account.name,
                "is_active": account.is_active,
                "guide_offset_hours": int(account.guide_offset_hours or 0),
                "global_epg_offset_minutes": global_offset_minutes,
            },
            "selected_channels": [],
            "sources": {},
        }
        secrets: list[str] = []
        client: Optional[XtreamClient] = None
        all_channels: list[dict] = []
        catchup_channels: list[dict] = []
        category_names: dict[str, str] = {}

        db_inventory = await _database_channel_inventory(session, account.id)

        try:
            password = resolve_account_password(account)
            secrets = [account.server_url, account.username, password]
            client = XtreamClient(account.server_url, account.username, password)

            try:
                categories = await client.get_live_categories()
                category_names = {
                    str(item.get("category_id")): str(item.get("category_name") or "")
                    for item in categories
                    if item.get("category_id") is not None
                }
            except Exception as exc:
                account_export.setdefault("source_errors", {})["provider_categories"] = str(exc)[:500]

            try:
                all_channels = await client.get_live_streams()
                catchup_channels = [
                    channel
                    for channel in all_channels
                    if int(channel.get("tv_archive", 0) or 0) == 1
                ]
            except Exception as exc:
                account_export.setdefault("source_errors", {})["provider_channels"] = str(exc)[:500]
        except Exception as exc:
            account_export.setdefault("source_errors", {})["provider_credentials"] = str(exc)[:500]

        provider_selected = _select_evenly(catchup_channels, channels_per_account)
        selected_channels = list(provider_selected)
        selected_ids = {
            str(channel.get("stream_id"))
            for channel in selected_channels
            if channel.get("stream_id") is not None
        }
        if len(selected_channels) < channels_per_account:
            for db_channel in _select_evenly(db_inventory, channels_per_account):
                stream_id = str(db_channel.get("stream_id") or "")
                if not stream_id or stream_id in selected_ids:
                    continue
                selected_channels.append(db_channel)
                selected_ids.add(stream_id)
                if len(selected_channels) >= channels_per_account:
                    break

        account_export["selected_channels"] = [
            _provider_channel_snapshot(channel, category_names, secrets)
            if "inventory_source" not in channel
            else dict(channel)
            for channel in selected_channels
        ]

        account_export["sources"]["provider_channels"] = {
            "source": "xtream_live_streams",
            "total_channels": len(all_channels),
            "catchup_channels": len(catchup_channels),
            "samples": [
                _provider_channel_snapshot(channel, category_names, secrets)
                for channel in _select_evenly(all_channels, channels_per_account)
            ],
        }

        raw_xmltv = b""
        if client is not None:
            try:
                raw_xmltv = await client.get_xmltv()
            except Exception as exc:
                account_export.setdefault("source_errors", {})["xmltv_raw"] = str(exc)[:500]
        account_export["sources"]["xmltv_raw"] = _sample_xmltv(
            raw_xmltv,
            catchup_channels,
            selected_ids,
            account.id,
            programs_per_channel,
            xmltv_overall_samples,
            secrets,
        )

        database_source, final_source = await _sample_database_and_final(
            session,
            account,
            selected_channels,
            programs_per_channel,
            global_offset_minutes,
        )
        account_export["sources"]["sqlite_epg_programs"] = database_source
        account_export["sources"]["mustarrd_final"] = final_source
        account_export["sources"]["live_epg_api"] = await _sample_live_api(
            client,
            account,
            selected_channels,
            programs_per_channel,
            global_offset_minutes,
            secrets,
        )

        if client is not None:
            await client.close()

        export["accounts"].append(account_export)

    return export
