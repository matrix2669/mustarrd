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
    return f"{{tmdb-{tmdb_id}}} [tmdbid-{tmdb_id}]"


def _render_relative_template(template: str, context: dict) -> list[str]:
    """Render a media template as safe relative path components."""
    components = []
    for component_template in template.split("/"):
        if not component_template.strip():
            continue
        rendered = component_template.format_map(context)
        rendered = re.sub(r"\s*\(\s*\)\s*", " ", rendered)
        rendered = re.sub(r"\s{2,}", " ", rendered).strip()
        rendered = re.sub(r"\s+-\s*$", "", rendered).strip()
        components.append(_sanitize_component(rendered))
    return components


def _movie_title_and_year(title: str, year: Optional[int]) -> tuple[str, Optional[int]]:
    safe_title = _sanitize_component(title)
    if year:
        clean_title = re.sub(r"\s*\(\d{4}\)\s*$", "", safe_title).strip() or safe_title
        return clean_title, year
    return safe_title, None


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
        components = _render_relative_template(selected_template, context)
    except (KeyError, ValueError, AttributeError):
        components = []

    if not components:
        fallback = clean_title
        if normalized_year:
            fallback = f"{fallback} ({normalized_year})"
        components = [_sanitize_component(fallback)]

    filename = f"{components[-1]}.{_safe_extension(extension)}"
    return os.path.join(download_folder, *components[:-1], filename)


def _legacy_series_components(
    show_name: str,
    season_num: int,
    episode_num: int,
    episode_title: Optional[str],
    episode_id: Optional[str],
) -> list[str]:
    safe_show = _sanitize_component(show_name)
    safe_title = _sanitize_component(episode_title) if episode_title else ""
    season_folder = f"Season {season_num:02d}"
    base_name = f"S{season_num:02d}E{episode_num:02d} - {safe_show}"
    if safe_title:
        base_name = f"{base_name} - {safe_title}"
    elif episode_num <= 0 and episode_id:
        base_name = f"{base_name} - {_sanitize_component(str(episode_id))}"
    return [safe_show, season_folder, _sanitize_component(base_name)]


def series_episode_output_path(
    download_folder: str,
    show_name: str,
    season: int,
    episode: int,
    episode_title: Optional[str],
    extension: Optional[str],
    episode_id: Optional[str] = None,
    template: Optional[str] = None,
    tmdb_id=None,
) -> str:
    safe_show = _sanitize_component(show_name)
    safe_title = _sanitize_component(episode_title) if episode_title else ""
    season_num = int(season or 0)
    episode_num = int(episode or 0)

    if template:
        context = {
            "show": safe_show,
            "season": season_num,
            "episode": episode_num,
            "title": safe_title,
            "tmdb": _tmdb_tags(tmdb_id),
            "tmdb_id": _numeric_tmdb_id(tmdb_id),
        }
        try:
            components = _render_relative_template(template, context)
        except (KeyError, ValueError, AttributeError):
            components = []
    else:
        components = []

    # Old installs/test fixtures that genuinely have no tv_template retain the
    # previous VOD hierarchy. Normal persisted AppSettings rows have a
    # tv_template, making that configured template authoritative for VOD too.
    if not components:
        components = _legacy_series_components(
            safe_show,
            season_num,
            episode_num,
            safe_title,
            episode_id,
        )

    final_component = components[-1]
    encoded = final_component.encode("utf-8")
    if len(encoded) > 200:
        final_component = encoded[:200].decode("utf-8", errors="ignore").rstrip() or "unknown-episode"

    filename = f"{final_component}.{_safe_extension(extension)}"
    return os.path.join(download_folder, *components[:-1], filename)
