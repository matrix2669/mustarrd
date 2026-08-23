"""Structured metadata Mustarrd keeps for a guide program.

This module owns the field list. Adding another structured field means editing
this file only: declare the column on ``GuideMetadataColumns``, add a ``_Field``
to ``_FIELDS``, and the startup migration, the row projection and the guide
payload all pick it up.

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
from typing import Any, Callable, ClassVar, Optional

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column


class GuideMetadataColumns:
    """The epg_programs columns holding structured guide metadata.

    Mixed into the EPGProgram model. Every column here has a matching entry in
    ``_FIELDS`` below; ``test_guide_metadata`` fails if the two drift apart.
    """

    subtitle: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    # The full category list as JSON. The first category also goes to the
    # pre-existing "category" column, so everything reading it keeps working.
    categories_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    season_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    episode_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    episode_num_onscreen: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    episode_num_xmltv: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    gracenote_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    tvdb_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    tmdb_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    imdb_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)


def _clean_text(value: Any) -> Optional[str]:
    """Blank and whitespace-only values are absent, not empty."""
    if value is None:
        return None
    text_value = str(value).strip()
    return text_value or None


def _clean_int(value: Any) -> Optional[int]:
    """Anything that is not a whole number is absent.

    Zero is kept: an on-screen S00E01 is the specials season, not a bad parse.
    Negatives are not: providers use -1 to mean "unknown".
    """
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


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


def _decode_categories(raw) -> tuple[str, ...]:
    if not raw:
        return ()
    if isinstance(raw, (list, tuple)):
        return _dedupe_categories(raw)
    try:
        decoded = json.loads(raw)
    except (TypeError, ValueError):
        return _dedupe_categories([raw])
    return _dedupe_categories(decoded if isinstance(decoded, list) else [decoded])


@dataclass(frozen=True)
class _Codec:
    """How one kind of field crosses the storage and API boundaries."""

    from_storage: Callable[[Any], Any]
    to_storage: Callable[[Any], Any]
    to_api: Callable[[Any], Any]


_TEXT = _Codec(from_storage=_clean_text, to_storage=lambda v: v, to_api=lambda v: v)
_INT = _Codec(from_storage=_clean_int, to_storage=lambda v: v, to_api=lambda v: v)
_CATEGORY_LIST = _Codec(
    from_storage=_decode_categories,
    to_storage=lambda v: json.dumps(list(v)) if v else None,
    to_api=list,
)


@dataclass(frozen=True)
class _Field:
    """One structured metadata field and everything the app needs to know about it."""

    name: str      # attribute on GuideMetadata and key in the guide payload
    column: str    # column on epg_programs, declared in GuideMetadataColumns
    ddl: str       # column type for the startup ALTER TABLE migration
    codec: _Codec


_FIELDS: tuple[_Field, ...] = (
    _Field("subtitle", "subtitle", "VARCHAR(500)", _TEXT),
    _Field("categories", "categories_json", "TEXT", _CATEGORY_LIST),
    _Field("season_number", "season_number", "INTEGER", _INT),
    _Field("episode_number", "episode_number", "INTEGER", _INT),
    _Field("episode_num_onscreen", "episode_num_onscreen", "VARCHAR(255)", _TEXT),
    _Field("episode_num_xmltv", "episode_num_xmltv", "VARCHAR(255)", _TEXT),
    _Field("gracenote_id", "gracenote_id", "VARCHAR(128)", _TEXT),
    _Field("tvdb_id", "tvdb_id", "VARCHAR(128)", _TEXT),
    _Field("tmdb_id", "tmdb_id", "VARCHAR(128)", _TEXT),
    _Field("imdb_id", "imdb_id", "VARCHAR(128)", _TEXT),
)

# The single-category column that predates this module, kept in sync with
# categories[0] so nothing reading it has to change.
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


def _parse_onscreen(raw: Optional[str]) -> tuple[Optional[int], Optional[int]]:
    if not raw:
        return None, None
    match = _ONSCREEN_SE_RE.search(raw) or _ONSCREEN_X_RE.search(raw)
    if match:
        return _clean_int(match.group(1)), _clean_int(match.group(2))
    return None, None


def _parse_xmltv_ns(raw: Optional[str]) -> tuple[Optional[int], Optional[int]]:
    """XMLTV's ``season.episode.part`` form is zero-based; convert to one-based.

    A negative value (providers use -1 for "unknown") stays absent rather than
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


def _is_absent(value: Any) -> bool:
    """Season 0 is a real season, so absence is not the same as falsiness."""
    return value is None or value == ()


def _first_present(entry: dict, *keys: str) -> Any:
    for key in keys:
        if key in entry:
            return entry[key]
    return None


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
    COLUMN_NAMES: ClassVar[tuple[str, ...]] = (_PRIMARY_CATEGORY_COLUMN,) + tuple(
        f.column for f in _FIELDS
    )
    # The columns this module added, for the startup migration.
    NEW_COLUMN_NAMES: ClassVar[tuple[str, ...]] = tuple(f.column for f in _FIELDS)

    @property
    def primary_category(self) -> Optional[str]:
        return self.categories[0] if self.categories else None

    @property
    def season_episode(self) -> Optional[tuple[int, int]]:
        """Both numbers, or nothing.

        One without the other is not usable numbering: a filename reading
        ``S03E00`` is worse than one with no numbering at all. Callers that
        want a season and an episode ask for the pair, so the rule lives here
        rather than being re-derived by each of them.
        """
        if self.season_number is None or self.episode_number is None:
            return None
        return (self.season_number, self.episode_number)

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
            elif tag == "episode-num" and value:
                system = (child.get("system") or "").strip().lower()
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
        """Read a provider guide entry, or a guide payload of our own shape."""
        entry = entry or {}
        categories = entry.get("categories") or [entry.get(_PRIMARY_CATEGORY_COLUMN)]

        onscreen = _clean_text(
            _first_present(entry, "episode_num_onscreen", "episode_onscreen")
        )
        xmltv_ns = _clean_text(
            _first_present(entry, "episode_num_xmltv", "episode_xmltv_ns")
        )
        season = _clean_int(_first_present(entry, "season_number", "season"))
        episode = _clean_int(_first_present(entry, "episode_number", "episode"))
        if season is None and episode is None:
            season, episode = cls._pick_season_episode(
                _parse_onscreen(onscreen), _parse_xmltv_ns(xmltv_ns)
            )

        return cls(
            subtitle=_clean_text(_first_present(entry, "subtitle", "sub_title")),
            categories=_dedupe_categories(categories),
            season_number=season,
            episode_number=episode,
            episode_num_onscreen=onscreen,
            episode_num_xmltv=xmltv_ns,
            gracenote_id=_clean_text(
                _first_present(entry, "gracenote_id", "dd_progid")
            ),
            tvdb_id=_clean_text(entry.get("tvdb_id")),
            tmdb_id=_clean_text(entry.get("tmdb_id")),
            imdb_id=_clean_text(entry.get("imdb_id")),
        )

    @classmethod
    def from_row(cls, row) -> "GuideMetadata":
        """Read a stored guide row (an EPGProgram, or anything shaped like one)."""
        values = {
            f.name: f.codec.from_storage(getattr(row, f.column, None)) for f in _FIELDS
        }

        # Read databases created by the matrix2669 fork before upstream
        # standardized these three column names. Startup migration copies the
        # values forward; these fallbacks also keep pre-migration row-shaped
        # objects safe in tests and maintenance tools.
        legacy_columns = {
            "episode_num_onscreen": "episode_onscreen",
            "episode_num_xmltv": "episode_xmltv_ns",
            "gracenote_id": "dd_progid",
        }
        for current_name, legacy_name in legacy_columns.items():
            if _is_absent(values[current_name]):
                values[current_name] = _clean_text(getattr(row, legacy_name, None))

        # Rows written before this module have only the single category column.
        if not values["categories"]:
            values["categories"] = _dedupe_categories(
                [getattr(row, _PRIMARY_CATEGORY_COLUMN, None)]
            )

        return cls(**values)

    # --- projections --------------------------------------------------

    def to_columns(self) -> dict:
        """The database columns for this metadata, ready to merge into a row dict."""
        columns = {f.column: f.codec.to_storage(getattr(self, f.name)) for f in _FIELDS}
        columns[_PRIMARY_CATEGORY_COLUMN] = self.primary_category
        return columns

    def to_api(self) -> dict:
        """The guide-payload shape. Every key is nullable and additive.

        Includes the pre-existing single-category key, so a guide payload gets
        its whole metadata from one call and no caller has to know that
        ``category`` is the first of ``categories``.
        """
        payload = {f.name: f.codec.to_api(getattr(self, f.name)) for f in _FIELDS}
        payload[_PRIMARY_CATEGORY_COLUMN] = self.primary_category
        # Temporary API aliases preserve the existing Dispatcharr plugin
        # contract while the fork moves to upstream's canonical field names.
        payload["episode_onscreen"] = payload["episode_num_onscreen"]
        payload["episode_xmltv_ns"] = payload["episode_num_xmltv"]
        payload["dd_progid"] = payload["gracenote_id"]
        return payload

    # --- merging ------------------------------------------------------

    def fill_gaps_from(self, other: "GuideMetadata") -> "GuideMetadata":
        """A copy of this metadata with missing fields taken from ``other``."""
        if other is None:
            return self
        filled = {
            f.name: getattr(other, f.name)
            for f in _FIELDS
            if _is_absent(getattr(self, f.name))
        }
        return replace(self, **filled) if filled else self

    # --- internals ----------------------------------------------------

    @staticmethod
    def _pick_season_episode(onscreen, xmltv_ns) -> tuple[Optional[int], Optional[int]]:
        """Prefer the on-screen form when it yields both numbers, else the XMLTV one.

        One form or the other, never a season from one paired with an episode
        from the other.
        """
        if onscreen[0] is not None and onscreen[1] is not None:
            return onscreen
        if xmltv_ns[0] is not None or xmltv_ns[1] is not None:
            return xmltv_ns
        return onscreen


def metadata_column_ddl() -> tuple[tuple[str, str], ...]:
    """(column, SQL type) for the startup ALTER TABLE migration."""
    return tuple((f.column, f.ddl) for f in _FIELDS)
