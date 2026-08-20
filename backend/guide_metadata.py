"""Structured metadata Mustarrd keeps for a guide program.

This module owns the field list. Adding another structured field means editing
this file only: the database columns, the startup migration, the model, the row
projection and the API payload are all generated from ``_FIELDS`` below.

Nothing else should reach for an individual metadata field on an XMLTV element,
a provider guide entry or a stored row. Ask this module instead:

    meta = GuideMetadata.from_xmltv_element(programme)   # guide ingest
    meta = GuideMetadata.from_guide_entry(entry)         # live provider response
    meta = GuideMetadata.from_row(row)                   # stored guide row

    row.update(meta.to_columns())                        # storage
    payload.update(meta.to_api())                        # guide payload
    merged = live_meta.fill_gaps_from(stored_meta)       # sparse live responses

The module lives at the backend root rather than under ``services/`` because
``models`` imports it, and ``services`` imports ``models``.
"""
import json
import re
from dataclasses import dataclass, field, replace
from typing import Any, ClassVar, Optional

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import mapped_column


@dataclass(frozen=True)
class _Field:
    """One structured metadata field and everything the app needs to know about it."""

    name: str           # attribute on GuideMetadata and key in the API payload
    column: str         # column on epg_programs
    ddl: str            # column type for the startup ALTER TABLE migration
    sa_type: Any        # column type for the model
    kind: str           # "text", "int" or "categories"
    new_column: bool = True  # False for columns that predate this module


_FIELDS: tuple[_Field, ...] = (
    _Field("subtitle", "subtitle", "VARCHAR(500)", String(500), "text"),
    # The full category list is stored as JSON; the first category also goes to
    # the pre-existing "category" column so everything reading it keeps working.
    _Field("categories", "categories_json", "TEXT", Text, "categories"),
    _Field("season_number", "season_number", "INTEGER", Integer, "int"),
    _Field("episode_number", "episode_number", "INTEGER", Integer, "int"),
    _Field("episode_num_onscreen", "episode_num_onscreen", "VARCHAR(255)", String(255), "text"),
    _Field("episode_num_xmltv", "episode_num_xmltv", "VARCHAR(255)", String(255), "text"),
    _Field("gracenote_id", "gracenote_id", "VARCHAR(128)", String(128), "text"),
    _Field("tvdb_id", "tvdb_id", "VARCHAR(128)", String(128), "text"),
    _Field("tmdb_id", "tmdb_id", "VARCHAR(128)", String(128), "text"),
    _Field("imdb_id", "imdb_id", "VARCHAR(128)", String(128), "text"),
)

# The pre-existing single-category column, kept in sync with categories[0].
_PRIMARY_CATEGORY_COLUMN = "category"

# XMLTV episode-num systems that carry an external identifier rather than a
# season/episode number.
_ID_SYSTEMS = {
    "dd_progid": "gracenote_id",
    "gracenote": "gracenote_id",
    "thetvdb.com": "tvdb_id",
    "tvdb.com": "tvdb_id",
    "tvdb": "tvdb_id",
    "themoviedb.org": "tmdb_id",
    "tmdb.org": "tmdb_id",
    "tmdb": "tmdb_id",
    "imdb.com": "imdb_id",
    "imdb": "imdb_id",
}

_ONSCREEN_SE_RE = re.compile(r"s\s*(\d{1,4})\s*[.\-_ ]?\s*e\s*(\d{1,4})", re.IGNORECASE)
_ONSCREEN_X_RE = re.compile(r"\b(\d{1,4})\s*x\s*(\d{1,4})\b", re.IGNORECASE)
_ONSCREEN_EP_ONLY_RE = re.compile(r"^\s*(?:ep(?:isode)?\.?\s*)?(\d{1,4})\s*$", re.IGNORECASE)


def _clean_text(value: Any) -> Optional[str]:
    """Blank and whitespace-only values are absent, not empty."""
    if value is None:
        return None
    text_value = str(value).strip()
    return text_value or None


def _clean_int(value: Any) -> Optional[int]:
    """Anything that is not a positive integer is absent."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _dedupe_categories(values) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values or ():
        cleaned = _clean_text(value)
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return tuple(result)


def _parse_onscreen(raw: Optional[str]) -> tuple[Optional[int], Optional[int]]:
    if not raw:
        return None, None
    match = _ONSCREEN_SE_RE.search(raw) or _ONSCREEN_X_RE.search(raw)
    if match:
        return _clean_int(match.group(1)), _clean_int(match.group(2))
    episode_only = _ONSCREEN_EP_ONLY_RE.match(raw)
    if episode_only:
        return None, _clean_int(episode_only.group(1))
    return None, None


def _parse_xmltv_ns(raw: Optional[str]) -> tuple[Optional[int], Optional[int]]:
    """XMLTV's ``season.episode.part`` form is zero-based; convert to one-based.

    A negative part (providers use -1 for "unknown") stays absent rather than
    becoming season 0.
    """
    if not raw:
        return None, None
    parts = raw.split(".")

    def _one_based(index: int) -> Optional[int]:
        if index >= len(parts):
            return None
        text_value = parts[index].split("/")[0].strip()
        if not text_value:
            return None
        try:
            number = int(text_value)
        except ValueError:
            return None
        return number + 1 if number >= 0 else None

    return _one_based(0), _one_based(1)


@dataclass(frozen=True)
class GuideMetadata:
    """The structured metadata a provider published for one guide program."""

    subtitle: Optional[str] = None
    categories: tuple[str, ...] = field(default=())
    season_number: Optional[int] = None
    episode_number: Optional[int] = None
    episode_num_onscreen: Optional[str] = None
    episode_num_xmltv: Optional[str] = None
    gracenote_id: Optional[str] = None
    tvdb_id: Optional[str] = None
    tmdb_id: Optional[str] = None
    imdb_id: Optional[str] = None

    # Every storage column this metadata owns, primary category included.
    COLUMN_NAMES: ClassVar[tuple[str, ...]] = ()
    # The columns added by this module, for the startup migration.
    NEW_COLUMN_NAMES: ClassVar[tuple[str, ...]] = ()

    @property
    def primary_category(self) -> Optional[str]:
        return self.categories[0] if self.categories else None

    # --- constructors -------------------------------------------------

    @classmethod
    def from_xmltv_element(cls, elem) -> "GuideMetadata":
        """Read a whole XMLTV <programme> element."""
        subtitle = None
        categories: list[str] = []
        episode_nums: dict[str, str] = {}
        external_ids: dict[str, str] = {}

        for child in elem:
            tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            value = _clean_text(child.text)
            if tag == "sub-title":
                subtitle = subtitle or value
            elif tag == "category":
                if value:
                    categories.append(value)
            elif tag == "episode-num":
                system = (child.get("system") or "").strip().lower()
                if not value:
                    continue
                id_attribute = _ID_SYSTEMS.get(system)
                if id_attribute:
                    external_ids.setdefault(id_attribute, value)
                elif system in ("onscreen", "xmltv_ns"):
                    episode_nums.setdefault(system, value)

        onscreen = episode_nums.get("onscreen")
        xmltv_ns = episode_nums.get("xmltv_ns")
        season, episode = cls._pick_season_episode(
            _parse_onscreen(onscreen), _parse_xmltv_ns(xmltv_ns)
        )

        return cls(
            subtitle=subtitle,
            categories=_dedupe_categories(categories),
            season_number=season,
            episode_number=episode,
            episode_num_onscreen=onscreen,
            episode_num_xmltv=xmltv_ns,
            **external_ids,
        )

    @classmethod
    def from_guide_entry(cls, entry: dict) -> "GuideMetadata":
        """Read a provider guide entry (or an already-normalized program dict)."""
        entry = entry or {}
        categories = entry.get("categories")
        if not categories:
            categories = [entry.get("category") or entry.get("genre")]

        onscreen = _clean_text(entry.get("episode_num_onscreen"))
        xmltv_ns = _clean_text(entry.get("episode_num_xmltv"))
        season = _clean_int(entry.get("season_number") if "season_number" in entry else entry.get("season"))
        episode = _clean_int(
            entry.get("episode_number") if "episode_number" in entry else entry.get("episode")
        )
        if season is None and episode is None:
            season, episode = cls._pick_season_episode(
                _parse_onscreen(onscreen), _parse_xmltv_ns(xmltv_ns)
            )

        return cls(
            subtitle=_clean_text(entry.get("subtitle") or entry.get("sub_title")),
            categories=_dedupe_categories(categories),
            season_number=season,
            episode_number=episode,
            episode_num_onscreen=onscreen,
            episode_num_xmltv=xmltv_ns,
            gracenote_id=_clean_text(entry.get("gracenote_id")),
            tvdb_id=_clean_text(entry.get("tvdb_id")),
            tmdb_id=_clean_text(entry.get("tmdb_id")),
            imdb_id=_clean_text(entry.get("imdb_id")),
        )

    @classmethod
    def from_row(cls, row) -> "GuideMetadata":
        """Read a stored guide row (an EPGProgram, or anything shaped like one)."""
        values: dict[str, Any] = {}
        for meta_field in _FIELDS:
            raw = getattr(row, meta_field.column, None)
            if meta_field.kind == "categories":
                values[meta_field.name] = _dedupe_categories(cls._decode_categories(raw))
            elif meta_field.kind == "int":
                values[meta_field.name] = _clean_int(raw)
            else:
                values[meta_field.name] = _clean_text(raw)

        # Rows written before this module have only the single category column.
        if not values["categories"]:
            values["categories"] = _dedupe_categories(
                [getattr(row, _PRIMARY_CATEGORY_COLUMN, None)]
            )

        return cls(**values)

    # --- projections --------------------------------------------------

    def to_columns(self) -> dict:
        """The database columns for this metadata, ready to merge into a row dict."""
        columns: dict[str, Any] = {_PRIMARY_CATEGORY_COLUMN: self.primary_category}
        for meta_field in _FIELDS:
            value = getattr(self, meta_field.name)
            if meta_field.kind == "categories":
                columns[meta_field.column] = json.dumps(list(value)) if value else None
            else:
                columns[meta_field.column] = value
        return columns

    def to_api(self) -> dict:
        """The guide-payload shape. Every key is nullable and additive."""
        payload: dict[str, Any] = {}
        for meta_field in _FIELDS:
            value = getattr(self, meta_field.name)
            payload[meta_field.name] = list(value) if meta_field.kind == "categories" else value
        return payload

    # --- merging ------------------------------------------------------

    def fill_gaps_from(self, other: "GuideMetadata") -> "GuideMetadata":
        """A copy of this metadata with missing fields taken from ``other``."""
        if other is None:
            return self
        filled = {
            meta_field.name: getattr(other, meta_field.name)
            for meta_field in _FIELDS
            if not getattr(self, meta_field.name)
        }
        return replace(self, **filled) if filled else self

    # --- internals ----------------------------------------------------

    @staticmethod
    def _pick_season_episode(onscreen, xmltv_ns) -> tuple[Optional[int], Optional[int]]:
        """Prefer the on-screen form when it yields both numbers."""
        for candidate in (onscreen, xmltv_ns):
            if candidate[0] is not None and candidate[1] is not None:
                return candidate
        return (
            onscreen[0] if onscreen[0] is not None else xmltv_ns[0],
            onscreen[1] if onscreen[1] is not None else xmltv_ns[1],
        )

    @staticmethod
    def _decode_categories(raw) -> list:
        if not raw:
            return []
        if isinstance(raw, (list, tuple)):
            return list(raw)
        try:
            decoded = json.loads(raw)
        except (TypeError, ValueError):
            return [raw]
        return decoded if isinstance(decoded, list) else [decoded]


GuideMetadata.COLUMN_NAMES = (_PRIMARY_CATEGORY_COLUMN,) + tuple(f.column for f in _FIELDS)
GuideMetadata.NEW_COLUMN_NAMES = tuple(f.column for f in _FIELDS if f.new_column)


def metadata_column_ddl() -> tuple[tuple[str, str], ...]:
    """(column, SQL type) for the startup ALTER TABLE migration."""
    return tuple((f.column, f.ddl) for f in _FIELDS if f.new_column)


def guide_metadata_mixin() -> type:
    """A declarative mixin carrying one column per metadata field."""
    namespace = {
        f.column: mapped_column(f.sa_type, nullable=True)
        for f in _FIELDS
        if f.new_column
    }
    return type("GuideMetadataColumns", (), namespace)
