"""Build the comskip.ini used for commercial detection.

The Settings page exposes a small set of Comskip tunables stored on
app_settings (comskip_detect_method, comskip_min_commercialbreak, ...).
At detection time the INI passed to Comskip is produced by taking a base
INI — the user's config-dir comskip.ini if present, else the bundled one —
and overriding those tunable keys with the stored values. Starting from
the base file keeps non-exposed keys working, most importantly
output_edl=1 which the post-processing pipeline depends on.

When custom INI mode is enabled, the user-supplied path bypasses generation
entirely and is passed to Comskip as-is after save-time and run-time checks.
"""
import asyncio
import logging
import os
import re
import stat
import tempfile
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

from config import ensure_config_files, _resolve_bundled_comskip_ini

logger = logging.getLogger(__name__)


class ComskipIniError(RuntimeError):
    """Raised when an explicitly selected Comskip INI cannot be used safely."""


TUNABLE_KEYS = (
    "detect_method",
    "max_commercialbreak",
    "min_commercialbreak",
    "max_commercial_size",
    "min_commercial_size",
    "always_keep_first_seconds",
    "always_keep_last_seconds",
    "remove_before",
    "remove_after",
    "connect_blocks_with_logo",
    "thread_count",
)

_KEY_LINE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=")


def validate_comskip_ini_path(path: str, *, custom: bool = False) -> str:
    """Require a readable regular INI file and return its normalized path."""
    label = "Custom Comskip INI" if custom else "Comskip INI"
    cleaned = path.strip()
    if not cleaned:
        raise ComskipIniError(f"{label} path is required")

    expanded_path = os.path.expanduser(cleaned)
    if not os.path.isabs(expanded_path):
        raise ComskipIniError(
            f"{label} path must be an absolute path as seen by Mustarrd "
            "(inside the container when using Docker)"
        )
    normalized_path = os.path.abspath(expanded_path)

    try:
        path_stat = os.stat(normalized_path)
    except FileNotFoundError as exc:
        raise ComskipIniError(f"{label} file was not found: {path}") from exc
    except OSError as exc:
        raise ComskipIniError(
            f"{label} path could not be checked: {exc.strerror or exc}"
        ) from exc

    if not stat.S_ISREG(path_stat.st_mode):
        raise ComskipIniError(f"{label} path is not a regular file: {path}")

    try:
        with open(normalized_path, "rb") as handle:
            handle.read(1)
    except OSError as exc:
        raise ComskipIniError(
            f"{label} file is not readable by Mustarrd: {exc.strerror or exc}"
        ) from exc
    return normalized_path


def tunable_overrides(settings) -> dict[str, int]:
    """Read the tunable values off an AppSettings row, skipping unset ones."""
    overrides: dict[str, int] = {}
    for key in TUNABLE_KEYS:
        value = getattr(settings, f"comskip_{key}", None)
        if value is not None:
            overrides[key] = int(value)
    return overrides


def render_comskip_ini(base_text: str, overrides: dict[str, int]) -> str:
    """Return base_text with `key=value` lines replaced by the overrides."""
    out: list[str] = []
    seen: set[str] = set()
    for line in base_text.splitlines():
        match = _KEY_LINE.match(line)
        key = match.group(1) if match else None
        if key in overrides:
            out.append(f"{key}={overrides[key]}")
            seen.add(key)
        else:
            out.append(line)
    missing = [key for key in overrides if key not in seen]
    if missing:
        out.append("; Values below managed by the Mustarrd Comskip settings page")
        for key in missing:
            out.append(f"{key}={overrides[key]}")
    return "\n".join(out) + "\n"


def _base_ini_text() -> str:
    config_dir = ensure_config_files()
    candidates = [config_dir / "comskip.ini"]
    bundled = _resolve_bundled_comskip_ini()
    if bundled is not None:
        candidates.append(bundled)
    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.warning("Could not read %s as comskip.ini base: %s", candidate, exc)
    return "output_edl=1\n"


def generate_comskip_ini(
    settings, runtime_overrides: Optional[dict[str, int]] = None
) -> Optional[str]:
    """Write a unique per-run INI in Mustarrd's config dir and return its path."""
    try:
        config_dir = ensure_config_files()
        overrides = tunable_overrides(settings)
        overrides.update(runtime_overrides or {})
        content = render_comskip_ini(_base_ini_text(), overrides)
        fd, tmp_path = tempfile.mkstemp(
            dir=str(config_dir),
            prefix=".mustarrd-comskip-",
            suffix=".ini",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(content)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        return tmp_path
    except Exception as exc:
        logger.warning("Failed to generate comskip.ini from settings: %s", exc)
        return None


def resolve_comskip_ini(
    settings, runtime_overrides: Optional[dict[str, int]] = None
) -> tuple[Optional[str], bool]:
    """Return the INI path and whether Mustarrd owns it as a temporary file."""
    if getattr(settings, "comskip_use_custom_ini", False):
        custom = (getattr(settings, "comskip_custom_ini_path", None) or "").strip()
        if not custom:
            raise ComskipIniError(
                "A custom Comskip INI path is required when custom INI mode is enabled"
            )
        return validate_comskip_ini_path(custom, custom=True), False

    generated = generate_comskip_ini(settings, runtime_overrides)
    if generated:
        return generated, True
    return getattr(settings, "comskip_ini_path", None), False


def cleanup_comskip_ini(path: Optional[str], is_temporary: bool) -> None:
    """Remove a generated INI while leaving custom and legacy files untouched."""
    if not path or not is_temporary:
        return
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    except OSError as exc:
        logger.warning("Could not remove temporary Comskip INI %s: %s", path, exc)


@asynccontextmanager
async def resolved_comskip_ini(
    settings, runtime_overrides: Optional[dict[str, int]] = None
) -> AsyncIterator[Optional[str]]:
    """Resolve one run's INI and clean owned files even when resolution is cancelled."""
    path: Optional[str] = None
    is_temporary = False
    resolve_task = asyncio.create_task(
        asyncio.to_thread(resolve_comskip_ini, settings, runtime_overrides)
    )
    try:
        try:
            path, is_temporary = await asyncio.shield(resolve_task)
        except asyncio.CancelledError:
            try:
                path, is_temporary = await resolve_task
            except Exception:
                pass
            raise
        yield path
    finally:
        await asyncio.to_thread(cleanup_comskip_ini, path, is_temporary)
