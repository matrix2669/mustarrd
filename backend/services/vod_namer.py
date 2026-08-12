import os
import re
from typing import Optional

from services.file_namer import file_namer


_DEFAULT_MOVIE_TEMPLATE = "{title} ({year})"
_TMDB_ID_PATTERN = re.compile(r"(?:^|/)(\d+)(?:/?$)")


def _sanitize_component(value: str) -> str:
    return file_namer.sanitize_filename(value or "Unknown")


def _safe_extension(ext: Optional[str]) -> str:
    if not ext:
        return "mp4"
    cleaned = ext.strip().lstrip(".")
    if not cleaned:
        return "mp4"
    if not re.fullmatch(r"[A-Za-z0-9]{1,8}", cleaned):
        return "mp4"
    return cleaned.lower()


def _numeric_tmdb_id(value) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    match = _TMDB_ID_PATTERN.search(text)
    return match.group(1) if match else ""


def _tmdb_tags(value) -> str:
    tmdb_id = _numeric_tmdb_id(value)
    if not tmdb_id:
        return ""
    return f"{{tmdb-{tmdb_id}}} [tmdbid={tmdb_id}]"


def _movie_title_and_year(title: str, year: Optional[int]) -> tuple[str, Optional[int]]:
    safe_title = _sanitize_component(title)
    if year:
        clean_title = re.sub(r"\s*\(\d{4}\)\s*$", "", safe_title).strip() or safe_title
        return clean_title, year
    return safe_title, None


def _render_movie_template(template: str, context: dict) -> list[str]:
    """Render a VOD movie template as safe relative path components."""
    components = []
    for component_template in template.split("/"):
        if not component_template.strip():
            continue
        rendered = component_template.format_map(context)
        # When optional metadata is unavailable, avoid artifacts such as
        # "Movie ()" or doubled spaces around an empty {tmdb} token.
        rendered = re.sub(r"\s*\(\s*\)\s*", " ", rendered)
        components.append(_sanitize_component(rendered))
    return components


def movie_output_path(
    download_folder: str,
    title: str,
    year: Optional[int],
    extension: Optional[str],
    template: Optional[str] = None,
    tmdb_id=None,
) -> str:
    clean_title, normalized_year = _movie_title_and_year(title, year)
    context = {
        "title": clean_title,
        "year": normalized_year or "",
        "tmdb": _tmdb_tags(tmdb_id),
        "tmdb_id": _numeric_tmdb_id(tmdb_id),
    }

    selected_template = template or _DEFAULT_MOVIE_TEMPLATE
    try:
        components = _render_movie_template(selected_template, context)
    except (KeyError, ValueError, AttributeError):
        components = []

    if not components:
        fallback = clean_title
        if normalized_year:
            fallback = f"{fallback} ({normalized_year})"
        components = [_sanitize_component(fallback)]

    filename = f"{components[-1]}.{_safe_extension(extension)}"
    return os.path.join(download_folder, *components[:-1], filename)


def series_episode_output_path(
    download_folder: str,
    show_name: str,
    season: int,
    episode: int,
    episode_title: Optional[str],
    extension: Optional[str],
    episode_id: Optional[str] = None,
) -> str:
    safe_show = _sanitize_component(show_name)
    safe_title = _sanitize_component(episode_title) if episode_title else ""
    # Preserve raw values so negative season/episode numbers (common with
    # non-conforming providers) produce distinct paths rather than colliding
    # with genuine season=0/episode=0 entries.
    season_num = int(season or 0)
    episode_num = int(episode or 0)

    season_folder = f"Season {season_num:02d}"
    base_name = f"S{season_num:02d}E{episode_num:02d} - {safe_show}"
    if safe_title:
        base_name = f"{base_name} - {safe_title}"
    elif episode_num <= 0 and episode_id:
        # No usable title and no real episode number: append the provider
        # episode ID so multiple untitled zero-episode entries get distinct
        # output paths. Leave normal numbered episodes (S02E05, etc.) clean.
        base_name = f"{base_name} - {_sanitize_component(str(episode_id))}"

    # Cap combined base_name so the filename stays under Linux NAME_MAX (255
    # bytes). Each component is independently capped at 200 bytes by
    # sanitize_filename, but two components together can reach ~400 bytes.
    encoded = base_name.encode("utf-8")
    if len(encoded) > 200:
        base_name = encoded[:200].decode("utf-8", errors="ignore").rstrip() or "unknown-episode"

    filename = f"{base_name}.{_safe_extension(extension)}"

    return os.path.join(download_folder, safe_show, season_folder, filename)
