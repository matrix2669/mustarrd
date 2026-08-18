#!/usr/bin/env python3
import subprocess
import sys
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
        raise RuntimeError(f"anchor not found in {path}: {old[:100]!r}")
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

    # Fixtures were copied to /tmp by the workflow before reset.
    Path("backend/services/epg_metadata.py").write_text(Path("/tmp/pr408-epg_metadata.py").read_text())
    Path("backend/tests/test_structured_epg_ingest.py").write_text(
        Path("/tmp/pr408-test_structured_epg_ingest.py").read_text()
    )

    replace_once(
        "backend/models/epg_program.py",
        '''    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(255), nullable=True)
''',
        '''    title: Mapped[str] = mapped_column(String(500))
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
''',
    )

    replace_once(
        "backend/database.py",
        '''    if not await _column_exists(conn, "epg_programs", "provider_stop"):
        await conn.execute(text("ALTER TABLE epg_programs ADD COLUMN provider_stop VARCHAR(255)"))
''',
        '''    if not await _column_exists(conn, "epg_programs", "provider_stop"):
        await conn.execute(text("ALTER TABLE epg_programs ADD COLUMN provider_stop VARCHAR(255)"))

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
''',
    )

    ingest = Path("backend/services/epg_ingest_manager.py")
    text = ingest.read_text()
    text = text.replace(
        "from services.log_stream import backend_log_stream\n",
        "from services.log_stream import backend_log_stream\nfrom services.epg_metadata import extract_xmltv_metadata\n",
        1,
    )
    old = '''            "category": stmt.excluded.category,
            # Repair rows missing the provider-local start/stop'''
    new = '''            "category": func.coalesce(stmt.excluded.category, EPGProgram.category),
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
    if old not in text:
        raise RuntimeError("insert statement anchor missing")
    text = text.replace(old, new, 1)
    old = '''                title = self._extract_text(elem, "title") or "Unknown"
                description = self._extract_text(elem, "desc")
                category = self._extract_text(elem, "category")
'''
    new = '''                title = self._extract_text(elem, "title") or "Unknown"
                description = self._extract_text(elem, "desc")
                metadata = extract_xmltv_metadata(elem)
                category = metadata.get("category") or self._extract_text(elem, "category")
'''
    if old not in text:
        raise RuntimeError("ingest metadata anchor missing")
    text = text.replace(old, new, 1)
    old = '''                        "category": category,
                        "start_time": start_utc,'''
    new = '''                        "category": category,
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
    if old not in text:
        raise RuntimeError("ingest yield anchor missing")
    ingest.write_text(text.replace(old, new, 1))

    service = Path("backend/services/epg_service.py")
    text = service.read_text()
    text = text.replace(
        "from services.xtream_client import XtreamClient\n",
        "from services.xtream_client import XtreamClient\nfrom services.epg_metadata import decode_categories, metadata_from_live_entry\n",
        1,
    )
    text = text.replace(
        '        channel_id = str(entry.get("channel_id") or fallback_channel_id or "")\n',
        '        channel_id = str(entry.get("stream_id") or fallback_channel_id or entry.get("channel_id") or "")\n',
        1,
    )
    old = '''        return {
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
    new = '''        result = {
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
    if old not in text:
        raise RuntimeError("process-entry return anchor missing")
    text = text.replace(old, new, 1)
    old = '''            "channel_name": row.channel_name,
            "category": row.category,
        }
'''
    new = '''            "channel_name": row.channel_name,
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
    if old not in text:
        raise RuntimeError("serialize anchor missing")
    text = text.replace(old, new, 1)
    old = '''            if live_programs:
                self._cache[cache_key] = {
                    "data": live_programs,
                    "cached_at": datetime.utcnow()
                }
                return live_programs
'''
    new = '''            if live_programs:
                live_programs = await self._enrich_live_from_stored(
                    session, account_id, channel_id, live_programs, account, global_offset_minutes
                )
                self._cache[cache_key] = {
                    "data": live_programs,
                    "cached_at": datetime.utcnow()
                }
                return live_programs
'''
    if old not in text:
        raise RuntimeError("prefer-live anchor missing")
    text = text.replace(old, new, 1)
    anchor = '''    def _filter_programs_by_cutoff(self, programs: list[dict], cutoff: datetime) -> list:
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
            key = (str(live.get("channel_id") or ""), live.get("start_timestamp"), live.get("stop_timestamp"))
            stored = stored_by_window.get(key)
            if not stored:
                enriched.append(live)
                continue
            merged = dict(live)
            for field in cls._STRUCTURED_ENRICH_FIELDS:
                if merged.get(field) in (None, "", []):
                    value = stored.get(field)
                    if value not in (None, "", []):
                        merged[field] = value
            enriched.append(merged)
        return enriched

    async def _enrich_live_from_stored(
        self, session: AsyncSession, account_id: int, channel_id: str,
        live_programs: list[dict], account: Optional[XtreamAccount], global_offset_minutes: int,
    ) -> list[dict]:
        starts = [int(item["start_timestamp"]) for item in live_programs if item.get("start_timestamp") is not None]
        if not starts:
            return live_programs
        db_result = await session.execute(
            select(EPGProgram).where(
                EPGProgram.account_id == account_id,
                EPGProgram.channel_id == str(channel_id),
                EPGProgram.start_timestamp.in_(starts),
            )
        )
        stored = [self.serialize_program(row, account, global_offset_minutes) for row in db_result.scalars().all()]
        return self._enrich_live_programs(live_programs, stored)

    def _filter_programs_by_cutoff(self, programs: list[dict], cutoff: datetime) -> list:
'''
    if anchor not in text:
        raise RuntimeError("service method insertion anchor missing")
    service.write_text(text.replace(anchor, methods, 1))

    changelog = Path("CHANGELOG.md")
    text = changelog.read_text()
    title = "### Improved: Fresh guide results keep structured XMLTV metadata"
    if title not in text:
        marker = "---\n\n"
        pos = text.index(marker) + len(marker)
        entry = '''## 2026-08-17

### Improved: Fresh guide results keep structured XMLTV metadata

**What you would notice:** Program details from XMLTV — including subtitles, all categories, season/episode numbers, and Gracenote/TVDB/TMDB/IMDb identifiers — are now retained when the guide is ingested. When Browse asks the provider for a fresh EPG row that omits those fields, Mustarrd fills only the missing metadata from the exact matching stored airing. The provider's fresh title, description, timing and archive state remain authoritative, and fresh results are never widened with older stored-only rows.

**What changed:** The EPG schema now stores structured XMLTV fields through the normal startup migration path, XMLTV ingest writes them directly, stored program serialization exposes them, and fresh EPG normalization canonicalizes provider channel identifiers to the requested Xtream stream ID before exact-airing enrichment. Existing SQLite databases are upgraded additively at startup.

---

'''
        changelog.write_text(text[:pos] + entry + text[pos:])

    git("add", "-A")
    git("diff", "--check")


def publish():
    git("add", "-A")
    git("commit", "-m", "Preserve structured EPG metadata")
    git("push", "origin", f"HEAD:refs/heads/{TARGET}", f"--force-with-lease=refs/heads/{TARGET}:{OLD_HEAD}")


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in {"prepare", "publish"}:
        raise SystemExit("usage: build_pr408_schema_v2.py prepare|publish")
    (prepare if sys.argv[1] == "prepare" else publish)()
