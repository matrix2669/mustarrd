#!/usr/bin/env python3
import subprocess
from pathlib import Path

UPSTREAM = "df494fe35bc25b93a08b736226e77210b38c83a2"
OLD_HEAD = "a0234b7e7669f4f14fe3f971c65acec2f031a515"
TARGET = "agent/structured-epg-enrichment"


def run(*args, check=True):
    p = subprocess.run(args, text=True, capture_output=True)
    if check and p.returncode:
        raise RuntimeError(f"command failed: {' '.join(args)}\n{p.stdout}\n{p.stderr}")
    return p


def git(*args, check=True):
    return run("git", *args, check=check)


def replace_once(path, old, new):
    path = Path(path)
    text = path.read_text()
    if old not in text:
        raise RuntimeError(f"anchor not found in {path}: {old[:120]!r}")
    path.write_text(text.replace(old, new, 1))


def prepare():
    git("config", "user.name", "matrix2669")
    git("config", "user.email", "jarred@jdscomputing.com")
    subprocess.run(["git", "remote", "remove", "upstream"], check=False)
    git("remote", "add", "upstream", "https://github.com/razzamatazm/mustarrd.git")
    git("fetch", "upstream", "main")
    git("fetch", "origin", TARGET)
    actual = git("rev-parse", "upstream/main").stdout.strip()
    if actual != UPSTREAM:
        raise RuntimeError(f"upstream moved: expected {UPSTREAM}, got {actual}")
    git("reset", "--hard", UPSTREAM)

    Path("backend/services/epg_metadata.py").write_text('''"""Structured EPG metadata parsing shared by XMLTV ingest and live EPG normalization."""

import json
import re
from xml.etree.ElementTree import Element

_ONSCREEN_RE = re.compile(r"\\bS(\\d{1,4})E(\\d{1,4})\\b", re.IGNORECASE)


def _local_tag(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def _text(value) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _dedupe(values):
    result = []
    seen = set()
    for value in values:
        value = _text(value)
        if not value:
            continue
        key = value.casefold()
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result


def parse_xmltv_ns(value: str | None) -> tuple[int | None, int | None, int | None]:
    """Return (raw season, display season, display episode) for xmltv_ns."""
    value = _text(value)
    if not value:
        return None, None, None
    parts = value.split(".")
    try:
        raw_season = int(parts[0]) if parts and parts[0] else None
    except ValueError:
        raw_season = None
    try:
        raw_episode = int(parts[1]) if len(parts) > 1 and parts[1] else None
    except ValueError:
        raw_episode = None
    season = raw_season + 1 if raw_season is not None else None
    episode = raw_episode + 1 if raw_episode is not None else None
    return raw_season, season, episode


def _onscreen_numbers(value: str | None) -> tuple[int | None, int | None]:
    value = _text(value)
    if not value:
        return None, None
    match = _ONSCREEN_RE.search(value)
    if not match:
        return None, None
    return int(match.group(1)), int(match.group(2))


def extract_xmltv_metadata(elem: Element) -> dict:
    categories = []
    subtitle = None
    values = {}
    for child in list(elem):
        tag = _local_tag(child.tag)
        text = _text(child.text)
        if tag == "category" and text:
            categories.append(text)
        elif tag == "sub-title" and subtitle is None:
            subtitle = text
        elif tag == "episode-num" and text:
            system = (child.get("system") or "").strip().lower()
            values[system] = text

    categories = _dedupe(categories)
    onscreen = values.get("onscreen")
    xmltv_ns = values.get("xmltv_ns")
    raw_xml_season, xml_season, xml_episode = parse_xmltv_ns(xmltv_ns)
    on_season, on_episode = _onscreen_numbers(onscreen)

    # A provider's explicit xmltv_ns season -1 means "season unknown" and is
    # authoritative even when its onscreen rendering happens to say S00.
    if raw_xml_season == -1:
        season_number, episode_number = xml_season, xml_episode
    elif on_season is not None or on_episode is not None:
        season_number, episode_number = on_season, on_episode
    else:
        season_number, episode_number = xml_season, xml_episode

    return {
        "subtitle": subtitle,
        "category": categories[0] if categories else None,
        "categories_json": json.dumps(categories, ensure_ascii=False) if categories else None,
        "season_number": season_number,
        "episode_number": episode_number,
        "episode_onscreen": onscreen,
        "episode_xmltv_ns": xmltv_ns,
        "dd_progid": values.get("dd_progid"),
        "tvdb_id": values.get("thetvdb.com"),
        "tmdb_id": values.get("themoviedb.org"),
        "imdb_id": values.get("imdb.com"),
    }


def decode_categories(value) -> list[str]:
    if isinstance(value, (list, tuple)):
        return _dedupe(value)
    if not value:
        return []
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            parsed = [value]
        if isinstance(parsed, list):
            return _dedupe(parsed)
    return []


def metadata_from_live_entry(entry: dict) -> dict:
    categories = decode_categories(entry.get("categories"))
    if not categories:
        categories = decode_categories(entry.get("categories_json"))
    primary = _text(entry.get("category"))
    if primary and all(primary.casefold() != item.casefold() for item in categories):
        categories.insert(0, primary)

    xmltv_ns = _text(entry.get("episode_xmltv_ns"))
    onscreen = _text(entry.get("episode_onscreen"))
    raw_xml_season, xml_season, xml_episode = parse_xmltv_ns(xmltv_ns)
    on_season, on_episode = _onscreen_numbers(onscreen)

    season = entry.get("season_number")
    episode = entry.get("episode_number")
    try:
        season = int(season) if season is not None and season != "" else None
    except (TypeError, ValueError):
        season = None
    try:
        episode = int(episode) if episode is not None and episode != "" else None
    except (TypeError, ValueError):
        episode = None

    if raw_xml_season == -1:
        season, episode = xml_season, xml_episode
    elif season is None and episode is None and (on_season is not None or on_episode is not None):
        season, episode = on_season, on_episode
    elif season is None and episode is None:
        season, episode = xml_season, xml_episode

    return {
        "subtitle": _text(entry.get("subtitle") or entry.get("sub_title")),
        "category": primary or (categories[0] if categories else None),
        "categories": categories,
        "season_number": season,
        "episode_number": episode,
        "episode_onscreen": onscreen,
        "episode_xmltv_ns": xmltv_ns,
        "dd_progid": _text(entry.get("dd_progid")),
        "tvdb_id": _text(entry.get("tvdb_id")),
        "tmdb_id": _text(entry.get("tmdb_id")),
        "imdb_id": _text(entry.get("imdb_id")),
    }
''')

    # Model: add structured columns directly.
    model = Path("backend/models/epg_program.py")
    text = model.read_text()
    replace = '''    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(255), nullable=True)
'''
    structured = '''    title: Mapped[str] = mapped_column(String(500))
    subtitle: Mapped[str | None] = mapped_column(String(500), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(255), nullable=True)
    categories_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    season_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    episode_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    episode_onscreen: Mapped[str | None] = mapped_column(String(100), nullable=True)
    episode_xmltv_ns: Mapped[str | None] = mapped_column(String(100), nullable=True)
    dd_progid: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tvdb_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tmdb_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    imdb_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
'''
    if replace not in text:
        raise RuntimeError("model anchor not found")
    model.write_text(text.replace(replace, structured, 1))

    # Normal startup migration path.
    database = Path("backend/database.py")
    text = database.read_text()
    anchor = '''    if not await _column_exists(conn, "epg_programs", "provider_stop"):
        await conn.execute(text("ALTER TABLE epg_programs ADD COLUMN provider_stop VARCHAR(255)"))
'''
    migration = anchor + '''

    structured_epg_columns = {
        "subtitle": "VARCHAR(500)",
        "categories_json": "TEXT",
        "season_number": "INTEGER",
        "episode_number": "INTEGER",
        "episode_onscreen": "VARCHAR(100)",
        "episode_xmltv_ns": "VARCHAR(100)",
        "dd_progid": "VARCHAR(100)",
        "tvdb_id": "VARCHAR(100)",
        "tmdb_id": "VARCHAR(100)",
        "imdb_id": "VARCHAR(100)",
    }
    for column_name, column_type in structured_epg_columns.items():
        if not await _column_exists(conn, "epg_programs", column_name):
            await conn.execute(
                text(f"ALTER TABLE epg_programs ADD COLUMN {column_name} {column_type}")
            )
'''
    if anchor not in text:
        raise RuntimeError("database migration anchor not found")
    database.write_text(text.replace(anchor, migration, 1))

    ingest = Path("backend/services/epg_ingest_manager.py")
    text = ingest.read_text()
    text = text.replace(
        "from services.log_stream import backend_log_stream\n",
        "from services.log_stream import backend_log_stream\nfrom services.epg_metadata import extract_xmltv_metadata\n",
        1,
    )
    insert_anchor = '''            "category": stmt.excluded.category,
            # Repair rows missing the provider-local start/stop'''
    insert_fields = '''            "category": func.coalesce(stmt.excluded.category, EPGProgram.category),
            "subtitle": func.coalesce(stmt.excluded.subtitle, EPGProgram.subtitle),
            "categories_json": func.coalesce(stmt.excluded.categories_json, EPGProgram.categories_json),
            "season_number": func.coalesce(stmt.excluded.season_number, EPGProgram.season_number),
            "episode_number": func.coalesce(stmt.excluded.episode_number, EPGProgram.episode_number),
            "episode_onscreen": func.coalesce(stmt.excluded.episode_onscreen, EPGProgram.episode_onscreen),
            "episode_xmltv_ns": func.coalesce(stmt.excluded.episode_xmltv_ns, EPGProgram.episode_xmltv_ns),
            "dd_progid": func.coalesce(stmt.excluded.dd_progid, EPGProgram.dd_progid),
            "tvdb_id": func.coalesce(stmt.excluded.tvdb_id, EPGProgram.tvdb_id),
            "tmdb_id": func.coalesce(stmt.excluded.tmdb_id, EPGProgram.tmdb_id),
            "imdb_id": func.coalesce(stmt.excluded.imdb_id, EPGProgram.imdb_id),
            # Repair rows missing the provider-local start/stop'''
    if insert_anchor not in text:
        raise RuntimeError("insert anchor not found")
    text = text.replace(insert_anchor, insert_fields, 1)
    meta_anchor = '''                title = self._extract_text(elem, "title") or "Unknown"
                description = self._extract_text(elem, "desc")
                category = self._extract_text(elem, "category")
'''
    meta_new = '''                title = self._extract_text(elem, "title") or "Unknown"
                description = self._extract_text(elem, "desc")
                metadata = extract_xmltv_metadata(elem)
                category = metadata.get("category") or self._extract_text(elem, "category")
'''
    if meta_anchor not in text:
        raise RuntimeError("ingest metadata anchor not found")
    text = text.replace(meta_anchor, meta_new, 1)
    yield_anchor = '''                        "category": category,
                        "start_time": start_utc,'''
    yield_new = '''                        "category": category,
                        "subtitle": metadata.get("subtitle"),
                        "categories_json": metadata.get("categories_json"),
                        "season_number": metadata.get("season_number"),
                        "episode_number": metadata.get("episode_number"),
                        "episode_onscreen": metadata.get("episode_onscreen"),
                        "episode_xmltv_ns": metadata.get("episode_xmltv_ns"),
                        "dd_progid": metadata.get("dd_progid"),
                        "tvdb_id": metadata.get("tvdb_id"),
                        "tmdb_id": metadata.get("tmdb_id"),
                        "imdb_id": metadata.get("imdb_id"),
                        "start_time": start_utc,'''
    if yield_anchor not in text:
        raise RuntimeError("ingest yield anchor not found")
    ingest.write_text(text.replace(yield_anchor, yield_new, 1))

    service = Path("backend/services/epg_service.py")
    text = service.read_text()
    text = text.replace(
        "from services.xtream_client import XtreamClient\n",
        "from services.xtream_client import XtreamClient\nfrom services.epg_metadata import decode_categories, metadata_from_live_entry\n",
        1,
    )
    channel_anchor = '        channel_id = str(entry.get("channel_id") or fallback_channel_id or "")\n'
    channel_new = '        channel_id = str(entry.get("stream_id") or fallback_channel_id or entry.get("channel_id") or "")\n'
    if channel_anchor not in text:
        raise RuntimeError("canonical channel anchor not found")
    text = text.replace(channel_anchor, channel_new, 1)
    return_anchor = '''        return {
            "id": entry.get("id"),
            "epg_id": epg_id,
            "title": title,
            "description": description,
            "start_time": start_time.isoformat() if start_time else None,
            "end_time": end_time.isoformat() if end_time else None,
            "start_timestamp": start_timestamp,
            "stop_timestamp": stop_timestamp,
            "provider_start": str(provider_start).strip() if provider_start is not None else None,
            "provider_stop": str(provider_stop).strip() if provider_stop is not None else None,
            "duration_minutes": duration_minutes,
            "has_archive": has_archive_fallback if raw_has_archive is None else (int(raw_has_archive or 0) == 1),
            "channel_id": channel_id or None,
        }
'''
    return_new = '''        result = {
            "id": entry.get("id"),
            "epg_id": epg_id,
            "title": title,
            "description": description,
            "start_time": start_time.isoformat() if start_time else None,
            "end_time": end_time.isoformat() if end_time else None,
            "start_timestamp": start_timestamp,
            "stop_timestamp": stop_timestamp,
            "provider_start": str(provider_start).strip() if provider_start is not None else None,
            "provider_stop": str(provider_stop).strip() if provider_stop is not None else None,
            "duration_minutes": duration_minutes,
            "has_archive": has_archive_fallback if raw_has_archive is None else (int(raw_has_archive or 0) == 1),
            "channel_id": channel_id or None,
        }
        result.update(metadata_from_live_entry(entry))
        return result
'''
    if return_anchor not in text:
        raise RuntimeError("process return anchor not found")
    text = text.replace(return_anchor, return_new, 1)

    serial_anchor = '''            "channel_name": row.channel_name,
            "category": row.category,
        }
'''
    serial_new = '''            "channel_name": row.channel_name,
            "category": getattr(row, "category", None),
            "categories": decode_categories(getattr(row, "categories_json", None)),
            "subtitle": getattr(row, "subtitle", None),
            "season_number": getattr(row, "season_number", None),
            "episode_number": getattr(row, "episode_number", None),
            "episode_onscreen": getattr(row, "episode_onscreen", None),
            "episode_xmltv_ns": getattr(row, "episode_xmltv_ns", None),
            "dd_progid": getattr(row, "dd_progid", None),
            "tvdb_id": getattr(row, "tvdb_id", None),
            "tmdb_id": getattr(row, "tmdb_id", None),
            "imdb_id": getattr(row, "imdb_id", None),
        }
'''
    if serial_anchor not in text:
        raise RuntimeError("serialize anchor not found")
    text = text.replace(serial_anchor, serial_new, 1)

    prefer_anchor = '''            if live_programs:
                self._cache[cache_key] = {
                    "data": live_programs,
                    "cached_at": datetime.utcnow()
                }
                return live_programs
'''
    prefer_new = '''            if live_programs:
                live_programs = await self._enrich_live_from_stored(
                    session, account_id, channel_id, live_programs, account, global_offset_minutes
                )
                self._cache[cache_key] = {
                    "data": live_programs,
                    "cached_at": datetime.utcnow()
                }
                return live_programs
'''
    if prefer_anchor not in text:
        raise RuntimeError("prefer-live anchor not found")
    text = text.replace(prefer_anchor, prefer_new, 1)

    method_anchor = '''    def _filter_programs_by_cutoff(self, programs: list[dict], cutoff: datetime) -> list:
'''
    methods = '''    _STRUCTURED_ENRICH_FIELDS = (
        "category", "categories", "subtitle", "season_number", "episode_number",
        "episode_onscreen", "episode_xmltv_ns", "dd_progid", "tvdb_id", "tmdb_id", "imdb_id",
    )

    @classmethod
    def _enrich_live_programs(cls, live_programs: list[dict], stored_programs: list[dict]) -> list[dict]:
        stored_by_window = {
            (str(item.get("channel_id") or ""), item.get("start_timestamp"), item.get("stop_timestamp")): item
            for item in stored_programs
        }
        enriched = []
        for live in live_programs:
            key = (
                str(live.get("channel_id") or ""),
                live.get("start_timestamp"),
                live.get("stop_timestamp"),
            )
            stored = stored_by_window.get(key)
            if not stored:
                enriched.append(live)
                continue
            merged = dict(live)
            # Live timing/archive/title/description remain authoritative. Only
            # missing structured metadata is borrowed from the exact stored airing.
            for field in cls._STRUCTURED_ENRICH_FIELDS:
                value = merged.get(field)
                if value is None or value == "" or value == []:
                    stored_value = stored.get(field)
                    if stored_value is not None and stored_value != "" and stored_value != []:
                        merged[field] = stored_value
            enriched.append(merged)
        return enriched

    async def _enrich_live_from_stored(
        self,
        session: AsyncSession,
        account_id: int,
        channel_id: str,
        live_programs: list[dict],
        account: Optional[XtreamAccount],
        global_offset_minutes: int,
    ) -> list[dict]:
        starts = [
            int(item["start_timestamp"])
            for item in live_programs
            if item.get("start_timestamp") is not None
        ]
        if not starts:
            return live_programs
        db_result = await session.execute(
            select(EPGProgram).where(
                EPGProgram.account_id == account_id,
                EPGProgram.channel_id == str(channel_id),
                EPGProgram.start_timestamp.in_(starts),
            )
        )
        stored = [
            self.serialize_program(row, account, global_offset_minutes)
            for row in db_result.scalars().all()
        ]
        return self._enrich_live_programs(live_programs, stored)

    def _filter_programs_by_cutoff(self, programs: list[dict], cutoff: datetime) -> list:
'''
    if method_anchor not in text:
        raise RuntimeError("service method anchor not found")
    service.write_text(text.replace(method_anchor, methods, 1))

    # Focused regressions: parse/storage shape, canonical live identity, and no cardinality widening.
    Path("backend/tests/test_structured_epg_ingest.py").write_text('''import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.epg_ingest_manager import EPGIngestManager
from services.epg_service import EPGService
from services.epg_metadata import extract_xmltv_metadata
from defusedxml import ElementTree as ET


class StructuredXmltvMetadataTests(unittest.TestCase):
    def test_preserves_categories_episode_numbers_and_external_ids(self):
        elem = ET.fromstring('''<programme><title>Murder, She Wrote</title><sub-title>Final Curtain</sub-title><category>Series</category><category>Mystery</category><episode-num system="onscreen">S09E11</episode-num><episode-num system="xmltv_ns">8.10.</episode-num><episode-num system="dd_progid">EP00002995.0202</episode-num><episode-num system="thetvdb.com">series/78049</episode-num><episode-num system="themoviedb.org">series/484</episode-num><episode-num system="imdb.com">tt0086765</episode-num></programme>''')
        metadata = extract_xmltv_metadata(elem)
        self.assertEqual(metadata["subtitle"], "Final Curtain")
        self.assertEqual(metadata["season_number"], 9)
        self.assertEqual(metadata["episode_number"], 11)
        self.assertIn('"Series"', metadata["categories_json"])
        self.assertIn('"Mystery"', metadata["categories_json"])
        self.assertEqual(metadata["dd_progid"], "EP00002995.0202")
        self.assertEqual(metadata["tvdb_id"], "series/78049")
        self.assertEqual(metadata["tmdb_id"], "series/484")
        self.assertEqual(metadata["imdb_id"], "tt0086765")

    def test_raw_unknown_xmltv_season_takes_precedence_over_onscreen_zero(self):
        elem = ET.fromstring('''<programme><episode-num system="onscreen">S00E158</episode-num><episode-num system="xmltv_ns">-1.157.</episode-num></programme>''')
        metadata = extract_xmltv_metadata(elem)
        self.assertEqual(metadata["season_number"], 0)
        self.assertEqual(metadata["episode_number"], 158)
        self.assertEqual(metadata["episode_xmltv_ns"], "-1.157.")

    def test_iter_programs_emits_structured_columns(self):
        xmltv = b'''<tv><programme channel="guide.id" start="20260817010000 +0000" stop="20260817020000 +0000"><title>Alice</title><sub-title>The Great Escape</sub-title><category>Series</category><category>Comedy</category><episode-num system="onscreen">S05E17</episode-num></programme></tv>'''
        manager = EPGIngestManager()
        maps = {
            "stream_by_xmltv_id": {"guide.id": ["3235"]},
            "stream_by_name": {},
            "stream_info": {"3235": {"name": "Antenna", "has_archive": True, "archive_days": 30}},
        }
        rows = list(manager._iter_programs(xmltv, maps, datetime(2026, 8, 17, tzinfo=timezone.utc)))
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["channel_id"], "3235")
        self.assertEqual(row["subtitle"], "The Great Escape")
        self.assertEqual(row["season_number"], 5)
        self.assertEqual(row["episode_number"], 17)
        self.assertIn('"Comedy"', row["categories_json"])


class FreshEpgEnrichmentTests(unittest.TestCase):
    def setUp(self):
        self.service = EPGService()

    def test_requested_stream_id_wins_over_provider_xmltv_channel_id(self):
        account = SimpleNamespace(guide_offset_hours=0)
        result = self.service._process_epg_entry(
            {"channel_id": "guide.id", "start_timestamp": 1000, "stop_timestamp": 2000},
            account,
            fallback_channel_id="3235",
        )
        self.assertEqual(result["channel_id"], "3235")
        self.assertEqual(result["epg_id"], "3235:1000:2000")

    def test_exact_live_row_inherits_only_missing_structured_metadata(self):
        live = [{
            "channel_id": "3235", "start_timestamp": 1000, "stop_timestamp": 2000,
            "title": "Alice", "description": "Fresh description", "has_archive": False,
        }]
        stored = [{
            "channel_id": "3235", "start_timestamp": 1000, "stop_timestamp": 2000,
            "title": "Alice stored", "description": "Stored description", "has_archive": True,
            "category": "Series", "categories": ["Series", "Comedy"],
            "subtitle": "The Great Escape", "season_number": 5, "episode_number": 17,
        }, {
            "channel_id": "3235", "start_timestamp": 3000, "stop_timestamp": 4000,
            "category": "Sports",
        }]
        result = self.service._enrich_live_programs(live, stored)
        self.assertEqual(len(result), 1, "stored-only rows must not widen fresh live results")
        self.assertEqual(result[0]["description"], "Fresh description")
        self.assertFalse(result[0]["has_archive"])
        self.assertEqual(result[0]["category"], "Series")
        self.assertEqual(result[0]["categories"], ["Series", "Comedy"])
        self.assertEqual(result[0]["subtitle"], "The Great Escape")
        self.assertEqual(result[0]["season_number"], 5)


if __name__ == "__main__":
    unittest.main()
''')

    # Focused changelog entry.
    changelog = Path("CHANGELOG.md")
    text = changelog.read_text()
    marker = "---\n\n"
    entry = '''## 2026-08-17

### Improved: Fresh guide results keep structured XMLTV metadata

**What you would notice:** Program details from XMLTV — including subtitles, all categories, season/episode numbers, and Gracenote/TVDB/TMDB/IMDb identifiers — are now retained when the guide is ingested. When Browse asks the provider for a fresh EPG row that omits those fields, Mustarrd fills only the missing metadata from the exact matching stored airing. The provider's fresh title, description, timing and archive state remain authoritative, and fresh results are never widened with older stored-only rows.

**What changed:** The EPG schema now stores structured XMLTV fields through the normal startup migration path, XMLTV ingest writes them directly, stored program serialization exposes them, and fresh EPG normalization canonicalizes provider channel identifiers to the requested Xtream stream ID before exact-airing enrichment. Existing SQLite databases are upgraded additively at startup.

---

'''
    if "### Improved: Fresh guide results keep structured XMLTV metadata" not in text:
        pos = text.index(marker) + len(marker)
        changelog.write_text(text[:pos] + entry + text[pos:])

    git("add", "-A")
    git("diff", "--check")


def publish():
    git("add", "-A")
    git("commit", "-m", "Preserve structured EPG metadata")
    git("push", "origin", f"HEAD:refs/heads/{TARGET}", f"--force-with-lease=refs/heads/{TARGET}:{OLD_HEAD}")


if __name__ == "__main__":
    if len(__import__('sys').argv) != 2 or __import__('sys').argv[1] not in {"prepare", "publish"}:
        raise SystemExit("usage: build_pr408_schema.py prepare|publish")
    (prepare if __import__('sys').argv[1] == "prepare" else publish)()
