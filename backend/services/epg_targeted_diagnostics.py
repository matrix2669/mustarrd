import io
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

from defusedxml import ElementTree as ET
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import AppSettings, EPGProgram, XtreamAccount
from services.account_credentials import resolve_account_password
from services.epg_diagnostics import (
    _local_tag,
    _provider_channel_snapshot,
    _scrub_value,
    _xmltv_program_snapshot,
)
from services.epg_ingest_manager import _sanitize_html_entities, epg_ingest_manager
from services.epg_service import epg_service
from services.xtream_client import XtreamClient


def _normalize_target(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


def _channel_name(channel: dict) -> str:
    return str(channel.get("name") or channel.get("channel_name") or "")


def _channel_id(channel: dict) -> str:
    return str(channel.get("stream_id") or channel.get("channel_id") or "")


def _db_channel_snapshot(channel_id: str, channel_name: str) -> dict:
    return {
        "stream_id": str(channel_id),
        "name": channel_name,
        "inventory_source": "database",
    }


async def _database_channel_inventory(session: AsyncSession, account_id: int) -> list[dict]:
    result = await session.execute(
        select(EPGProgram.channel_id, EPGProgram.channel_name)
        .where(EPGProgram.account_id == account_id)
        .group_by(EPGProgram.channel_id, EPGProgram.channel_name)
        .order_by(EPGProgram.channel_name.asc())
    )
    return [
        _db_channel_snapshot(str(channel_id), channel_name)
        for channel_id, channel_name in result.all()
    ]


def _resolve_targets(
    requested: list[str],
    provider_channels: list[dict],
    db_channels: list[dict],
) -> tuple[list[dict], list[dict], list[str]]:
    """Resolve stream IDs or channel names without silently guessing ambiguity."""
    provider_by_id = {
        _channel_id(channel): channel
        for channel in provider_channels
        if _channel_id(channel)
    }
    db_by_id = {
        _channel_id(channel): channel
        for channel in db_channels
        if _channel_id(channel)
    }
    all_channels = list(provider_channels) + [
        channel for channel in db_channels if _channel_id(channel) not in provider_by_id
    ]

    resolved: list[dict] = []
    ambiguous: list[dict] = []
    unmatched: list[str] = []
    seen_ids: set[str] = set()

    for raw_target in requested:
        target = (raw_target or "").strip()
        if not target:
            continue

        if target in provider_by_id:
            matches = [provider_by_id[target]]
        elif target in db_by_id:
            matches = [db_by_id[target]]
        else:
            normalized = _normalize_target(target)
            exact = [
                channel
                for channel in all_channels
                if _normalize_target(_channel_name(channel)) == normalized
            ]
            if exact:
                matches = exact
            else:
                partial = [
                    channel
                    for channel in all_channels
                    if normalized and normalized in _normalize_target(_channel_name(channel))
                ]
                matches = partial if len(partial) == 1 else []
                if len(partial) > 1:
                    ambiguous.append(
                        {
                            "requested": target,
                            "matches": [
                                {"stream_id": _channel_id(channel), "name": _channel_name(channel)}
                                for channel in partial[:25]
                            ],
                        }
                    )
                    continue

        unique_matches = []
        unique_ids: set[str] = set()
        for channel in matches:
            stream_id = _channel_id(channel)
            if stream_id and stream_id not in unique_ids:
                unique_matches.append(channel)
                unique_ids.add(stream_id)

        if len(unique_matches) == 1:
            stream_id = _channel_id(unique_matches[0])
            if stream_id not in seen_ids:
                resolved.append(unique_matches[0])
                seen_ids.add(stream_id)
        elif len(unique_matches) > 1:
            ambiguous.append(
                {
                    "requested": target,
                    "matches": [
                        {"stream_id": _channel_id(channel), "name": _channel_name(channel)}
                        for channel in unique_matches[:25]
                    ],
                }
            )
        else:
            unmatched.append(target)

    return resolved, ambiguous, unmatched


def _parse_xmltv_start(value: Optional[str]) -> Optional[datetime]:
    token = (value or "").strip()
    if not token:
        return None
    for fmt in (
        "%Y%m%d%H%M%S %z",
        "%Y%m%d%H%M %z",
        "%Y%m%d%H%M%S",
        "%Y%m%d%H%M",
    ):
        try:
            parsed = datetime.strptime(token, fmt)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def _distance_from_now(timestamp: Optional[datetime], now: datetime) -> float:
    if timestamp is None:
        return float("inf")
    return abs((timestamp - now).total_seconds())


def _closest(items: list[dict], limit: int, time_key) -> list[dict]:
    now = datetime.now(timezone.utc)
    ranked = sorted(items, key=lambda item: _distance_from_now(time_key(item), now))
    selected = ranked[: max(0, int(limit))]
    return sorted(
        selected,
        key=lambda item: time_key(item) or datetime.max.replace(tzinfo=timezone.utc),
    )


def _xmltv_direct_ids(channel: dict) -> set[str]:
    values = set()
    for key in ("epg_channel_id", "tvg_id", "tvgid", "tvg-id"):
        value = channel.get(key)
        if value is not None and str(value).strip():
            values.add(str(value).strip().lower())
    return values


def _sample_targeted_xmltv(
    raw_xmltv: bytes,
    catchup_channels: list[dict],
    selected_channels: list[dict],
    programs_per_channel: int,
    secrets: Iterable[str],
) -> dict:
    decompressed = epg_ingest_manager._maybe_decompress(raw_xmltv) if raw_xmltv else b""
    result: dict[str, Any] = {
        "source": "xmltv_raw_targeted",
        "downloaded_bytes": len(decompressed),
        "parse_ok": True,
        "by_selected_channel": {},
    }
    if not decompressed:
        return result

    selected_ids = {_channel_id(channel) for channel in selected_channels if _channel_id(channel)}
    direct_ids = {
        _channel_id(channel): _xmltv_direct_ids(channel)
        for channel in selected_channels
        if _channel_id(channel)
    }
    candidates: dict[str, list[dict]] = {stream_id: [] for stream_id in selected_ids}
    matched_counts: dict[str, int] = {stream_id: 0 for stream_id in selected_ids}

    channel_maps = epg_ingest_manager._build_channel_maps(catchup_channels)
    xmltv_to_stream, scan_ok = epg_ingest_manager._scan_channel_map(decompressed, channel_maps)
    result["parse_ok"] = scan_ok

    try:
        stream = io.BytesIO(_sanitize_html_entities(decompressed))
        for _, elem in ET.iterparse(stream, events=("end",)):
            if _local_tag(elem.tag) != "programme":
                continue

            xmltv_id = (elem.get("channel") or "").strip().lower()
            mapped_ids = {
                str(value)
                for value in epg_ingest_manager._as_stream_ids(
                    xmltv_to_stream.get(xmltv_id) if xmltv_id else None
                )
            }
            matched_streams = selected_ids.intersection(mapped_ids)
            for stream_id, ids in direct_ids.items():
                if xmltv_id and xmltv_id in ids:
                    matched_streams.add(stream_id)

            if matched_streams:
                snapshot = _xmltv_program_snapshot(elem, secrets)
                snapshot["mapped_stream_ids"] = sorted(mapped_ids)
                snapshot["xmltv_channel_id"] = xmltv_id or None
                parsed_start = _parse_xmltv_start(elem.get("start"))
                snapshot["parsed_start_utc"] = parsed_start.isoformat() if parsed_start else None
                for stream_id in matched_streams:
                    matched_counts[stream_id] += 1
                    candidates[stream_id].append(snapshot)

            elem.clear()
    except ET.ParseError as exc:
        result["parse_ok"] = False
        result["parse_error"] = str(exc)

    for channel in selected_channels:
        stream_id = _channel_id(channel)
        if not stream_id:
            continue
        selected = _closest(
            candidates.get(stream_id, []),
            programs_per_channel,
            lambda item: (
                datetime.fromisoformat(item["parsed_start_utc"])
                if item.get("parsed_start_utc")
                else None
            ),
        )
        result["by_selected_channel"][stream_id] = {
            "channel_name": _channel_name(channel),
            "programme_count_seen": matched_counts.get(stream_id, 0),
            "samples_nearest_now": selected,
        }

    return result


def _structured_row_snapshot(row: EPGProgram) -> dict:
    snapshot = {
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
    for field in (
        "subtitle",
        "categories_json",
        "season_number",
        "episode_number",
        "episode_onscreen",
        "episode_xmltv_ns",
        "dd_progid",
        "tvdb_id",
        "tmdb_id",
        "imdb_id",
    ):
        if hasattr(row, field):
            value = getattr(row, field, None)
            snapshot[field] = value
            if field == "categories_json" and value:
                try:
                    snapshot["categories"] = json.loads(value)
                except (TypeError, ValueError):
                    snapshot["categories"] = value
    return snapshot


def _classification_snapshot(program: dict, channel_name: str) -> dict:
    channel_context = {
        "name": channel_name,
        "stream_id": program.get("channel_id"),
        "category_name": program.get("category", "") or "",
    }
    return {
        "result": epg_service.detect_program_type(program, channel_context),
        "inputs": {
            "title": program.get("title"),
            "subtitle": program.get("subtitle"),
            "description": program.get("description"),
            "category": program.get("category"),
            "categories": program.get("categories"),
            "season_number": program.get("season_number"),
            "episode_number": program.get("episode_number"),
            "dd_progid": program.get("dd_progid"),
            "tvdb_id": program.get("tvdb_id"),
            "tmdb_id": program.get("tmdb_id"),
            "imdb_id": program.get("imdb_id"),
            "channel_name": channel_name,
        },
    }


async def _sample_targeted_database(
    session: AsyncSession,
    account: XtreamAccount,
    selected_channels: list[dict],
    programs_per_channel: int,
    global_offset_minutes: int,
) -> tuple[dict, dict]:
    database_source = {"source": "sqlite_epg_programs_targeted", "by_selected_channel": {}}
    final_source = {"source": "mustarrd_serialized_and_classified_targeted", "by_selected_channel": {}}

    now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
    window_start = now_naive - timedelta(days=3)
    window_end = now_naive + timedelta(days=3)

    for channel in selected_channels:
        stream_id = _channel_id(channel)
        channel_name = _channel_name(channel) or stream_id
        if not stream_id:
            continue

        result = await session.execute(
            select(EPGProgram)
            .where(
                EPGProgram.account_id == account.id,
                EPGProgram.channel_id == stream_id,
                EPGProgram.start_time >= window_start,
                EPGProgram.start_time <= window_end,
            )
            .order_by(EPGProgram.start_time.asc())
        )
        rows = result.scalars().all()
        used_fallback = False
        near_now_count = len(rows)
        if not rows:
            used_fallback = True
            fallback = await session.execute(
                select(EPGProgram)
                .where(
                    EPGProgram.account_id == account.id,
                    EPGProgram.channel_id == stream_id,
                )
                .order_by(EPGProgram.start_time.desc())
                .limit(max(50, programs_per_channel * 5))
            )
            rows = fallback.scalars().all()

        selected_rows = _closest(
            [{"row": row} for row in rows],
            programs_per_channel,
            lambda item: (
                item["row"].start_time.replace(tzinfo=timezone.utc)
                if item["row"].start_time and item["row"].start_time.tzinfo is None
                else item["row"].start_time
            ),
        )
        selected_row_objects = [item["row"] for item in selected_rows]

        database_source["by_selected_channel"][stream_id] = {
            "channel_name": channel_name,
            "rows_in_near_now_window": near_now_count,
            "used_latest_rows_fallback": used_fallback,
            "window_start_utc": window_start.isoformat() + "Z",
            "window_end_utc": window_end.isoformat() + "Z",
            "samples_nearest_now": [_structured_row_snapshot(row) for row in selected_row_objects],
        }

        final_samples = []
        for row in selected_row_objects:
            serialized = epg_service.serialize_program(row, account, global_offset_minutes)
            final_samples.append(
                {
                    "epg_id": row.epg_id,
                    "serialized_program": serialized,
                    "classification": _classification_snapshot(serialized, row.channel_name),
                }
            )
        final_source["by_selected_channel"][stream_id] = {
            "channel_name": channel_name,
            "samples_nearest_now": final_samples,
        }

    return database_source, final_source


async def _sample_targeted_live_api(
    client: Optional[XtreamClient],
    account: XtreamAccount,
    selected_channels: list[dict],
    programs_per_channel: int,
    global_offset_minutes: int,
    secrets: Iterable[str],
) -> dict:
    source = {"source": "xtream_live_epg_api_targeted", "by_selected_channel": {}}
    if client is None:
        source["error"] = "Provider client unavailable"
        return source

    for channel in selected_channels:
        stream_id = _channel_id(channel)
        channel_name = _channel_name(channel) or stream_id
        if not stream_id:
            continue
        result = {
            "channel_name": channel_name,
            "entries_returned": 0,
            "samples_nearest_now": [],
        }
        try:
            entries = await client.get_epg(stream_id)
            result["entries_returned"] = len(entries)
            processed_entries = []
            for entry in entries:
                processed = epg_service._process_epg_entry(
                    entry,
                    account,
                    fallback_channel_id=stream_id,
                    has_archive_fallback=True,
                    global_offset_minutes=global_offset_minutes,
                )
                processed_entries.append(
                    {
                        "raw_entry": _scrub_value(entry, secrets),
                        "raw_field_names": sorted(str(key) for key in entry.keys()),
                        "processed_by_mustarrd": processed,
                        "classification": _classification_snapshot(processed, channel_name),
                    }
                )
            result["samples_nearest_now"] = _closest(
                processed_entries,
                programs_per_channel,
                lambda item: (
                    datetime.fromtimestamp(
                        int(item["processed_by_mustarrd"].get("start_timestamp") or 0),
                        tz=timezone.utc,
                    )
                    if item["processed_by_mustarrd"].get("start_timestamp")
                    else None
                ),
            )
        except Exception as exc:
            result["error"] = str(exc)[:500]
        source["by_selected_channel"][stream_id] = result

    return source


async def export_targeted_epg_diagnostics(
    session: AsyncSession,
    account_id: int,
    channel_targets: list[str],
    programs_per_channel: int = 20,
) -> dict:
    """Inspect exact channels across provider, XMLTV, live API, SQLite and classifier paths."""
    account_result = await session.execute(
        select(XtreamAccount).where(XtreamAccount.id == account_id)
    )
    account = account_result.scalar_one_or_none()
    if account is None:
        return {
            "schema_version": 1,
            "purpose": "Targeted EPG channel diagnostics",
            "error": f"Account {account_id} not found",
        }

    settings_result = await session.execute(select(AppSettings))
    db_settings = settings_result.scalar_one_or_none()
    global_offset_minutes = int(getattr(db_settings, "epg_offset_minutes", 0) or 0)

    db_channels = await _database_channel_inventory(session, account.id)
    provider_channels: list[dict] = []
    catchup_channels: list[dict] = []
    category_names: dict[str, str] = {}
    secrets: list[str] = []
    client: Optional[XtreamClient] = None
    source_errors: dict[str, str] = {}

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
            source_errors["provider_categories"] = str(exc)[:500]
        try:
            provider_channels = await client.get_live_streams()
            catchup_channels = [
                channel
                for channel in provider_channels
                if int(channel.get("tv_archive", 0) or 0) == 1
            ]
        except Exception as exc:
            source_errors["provider_channels"] = str(exc)[:500]
    except Exception as exc:
        source_errors["provider_credentials"] = str(exc)[:500]

    selected_channels, ambiguous, unmatched = _resolve_targets(
        channel_targets,
        provider_channels,
        db_channels,
    )

    selected_snapshots = []
    provider_ids = {_channel_id(channel) for channel in provider_channels}
    for channel in selected_channels:
        if _channel_id(channel) in provider_ids:
            selected_snapshots.append(_provider_channel_snapshot(channel, category_names, secrets))
        else:
            selected_snapshots.append(dict(channel))

    export: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "Targeted EPG channel diagnostics",
        "account": {
            "id": account.id,
            "name": account.name,
            "guide_offset_hours": int(account.guide_offset_hours or 0),
            "global_epg_offset_minutes": global_offset_minutes,
        },
        "requested_channels": channel_targets,
        "resolution": {
            "selected_channels": selected_snapshots,
            "ambiguous": ambiguous,
            "unmatched": unmatched,
        },
        "sampling": {
            "programs_per_channel": programs_per_channel,
            "strategy": (
                "Only requested channels are inspected. XMLTV, live API and SQLite "
                "samples are chosen nearest the current UTC time so the export reflects "
                "the programs being checked now rather than a whole-account reservoir."
            ),
        },
        "sources": {},
    }
    if source_errors:
        export["source_errors"] = source_errors

    export["sources"]["provider_channels"] = {
        "source": "xtream_live_streams_targeted",
        "total_channels": len(provider_channels),
        "catchup_channels": len(catchup_channels),
        "selected": selected_snapshots,
    }

    raw_xmltv = b""
    if client is not None:
        try:
            raw_xmltv = await client.get_xmltv()
        except Exception as exc:
            export.setdefault("source_errors", {})["xmltv_raw"] = str(exc)[:500]

    export["sources"]["xmltv_raw"] = _sample_targeted_xmltv(
        raw_xmltv,
        catchup_channels,
        selected_channels,
        programs_per_channel,
        secrets,
    )

    database_source, final_source = await _sample_targeted_database(
        session,
        account,
        selected_channels,
        programs_per_channel,
        global_offset_minutes,
    )
    export["sources"]["sqlite_epg_programs"] = database_source
    export["sources"]["mustarrd_final"] = final_source
    export["sources"]["live_epg_api"] = await _sample_targeted_live_api(
        client,
        account,
        selected_channels,
        programs_per_channel,
        global_offset_minutes,
        secrets,
    )

    if client is not None:
        await client.close()

    return export
