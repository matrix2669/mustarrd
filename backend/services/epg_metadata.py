"""Structured EPG metadata parsing shared by XMLTV ingest and live EPG normalization."""

import json
import re
from xml.etree.ElementTree import Element

_ONSCREEN_RE = re.compile(r"\bS(\d{1,4})E(\d{1,4})\b", re.IGNORECASE)


def _local_tag(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def _text(value) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _dedupe(values) -> list[str]:
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
            values[(child.get("system") or "").strip().lower()] = text

    categories = _dedupe(categories)
    onscreen = values.get("onscreen")
    xmltv_ns = values.get("xmltv_ns")
    raw_xml_season, xml_season, xml_episode = parse_xmltv_ns(xmltv_ns)
    on_season, on_episode = _onscreen_numbers(onscreen)

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
