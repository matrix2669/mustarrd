from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] if ".github" in Path(__file__).parts else Path.cwd()


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    (ROOT / path).write_text(content, encoding="utf-8")


def replace(path: str, old: str, new: str, *, count: int = 1) -> None:
    content = read(path)
    found = content.count(old)
    if found != count:
        raise RuntimeError(f"{path}: expected {count} occurrence(s), found {found}: {old[:120]!r}")
    write(path, content.replace(old, new, count))


def replace_regex(path: str, pattern: str, replacement: str, *, count: int = 1) -> None:
    content = read(path)
    updated, replaced = re.subn(pattern, replacement, content, count=count, flags=re.DOTALL)
    if replaced != count:
        raise RuntimeError(f"{path}: expected {count} regex replacement(s), found {replaced}: {pattern}")
    write(path, updated)


write(
    "backend/services/comskip_ini.py",
    '''"""Build the comskip.ini used for commercial detection.

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

_KEY_LINE = re.compile(r"^\\s*([A-Za-z_][A-Za-z0-9_]*)\\s*=")


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
    return "\\n".join(out) + "\\n"


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
    return "output_edl=1\\n"


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
    """Resolve one run's INI and clean generated files on every normal exit."""
    path, is_temporary = await asyncio.to_thread(
        resolve_comskip_ini, settings, runtime_overrides
    )
    try:
        yield path
    finally:
        await asyncio.to_thread(cleanup_comskip_ini, path, is_temporary)
''',
)

replace("backend/api/settings.py", "import stat\n", "")
replace(
    "backend/api/settings.py",
    "from services.download_manager import download_manager\n",
    "from services.comskip_ini import ComskipIniError, validate_comskip_ini_path\n"
    "from services.download_manager import download_manager\n",
)
replace_regex(
    "backend/api/settings.py",
    r"\ndef _validate_custom_comskip_ini_path\(path: str\) -> str:\n.*?\n\ndef _probe_folder_writable",
    "\n\ndef _probe_folder_writable",
)
replace(
    "backend/api/settings.py",
    "    comskip_connect_blocks_with_logo: Optional[int] = Field(default=None, ge=0, le=1)\n",
    "    comskip_connect_blocks_with_logo: Optional[bool] = None\n",
)
replace(
    "backend/api/settings.py",
    "        settings.comskip_custom_ini_path = _validate_custom_comskip_ini_path(custom_ini_path)\n",
    "        try:\n            settings.comskip_custom_ini_path = validate_comskip_ini_path(\n                custom_ini_path, custom=True\n            )\n        except ComskipIniError as exc:\n            raise HTTPException(status_code=400, detail=str(exc)) from exc\n",
)

replace(
    "backend/models/settings.py",
    "    comskip_connect_blocks_with_logo: Mapped[int] = mapped_column(Integer, default=0)\n",
    "    comskip_connect_blocks_with_logo: Mapped[bool] = mapped_column(Boolean, default=True)\n",
)
replace(
    "backend/database.py",
    '("comskip_connect_blocks_with_logo", "INTEGER DEFAULT 0"),\n',
    '("comskip_connect_blocks_with_logo", "BOOLEAN DEFAULT 1"),\n',
)
replace("comskip.ini", "connect_blocks_with_logo=0", "connect_blocks_with_logo=1")

replace(
    "backend/services/download_manager.py",
    '''                from services.comskip_ini import resolve_comskip_ini

                custom_ini = (getattr(settings, "comskip_custom_ini_path", None) or "").strip()
                use_custom_ini = bool(
                    getattr(settings, "comskip_use_custom_ini", False) and custom_ini
                )
                runtime_overrides = {}
                if getattr(settings, "comskip_dynamic_ticker_tape", False) and not use_custom_ini:
                    dimensions = await post_processor.probe_video_dimensions(
                        current_path, log_callback=log_callback
                    )
                    if dimensions:
                        width, height = dimensions
                        ticker_tape = round(height / 9)
                        runtime_overrides["ticker_tape"] = ticker_tape
                        await log_callback(f"Comskip input dimensions: {width}x{height}.")
                        await log_callback(f"Comskip resolved ticker_tape: {ticker_tape} px.")

                comskip_ini_path = await asyncio.to_thread(
                    resolve_comskip_ini, settings, runtime_overrides
                )
                generated_ini = bool(
                    comskip_ini_path
                    and not use_custom_ini
                    and comskip_ini_path != getattr(settings, "comskip_ini_path", None)
                )
                try:
                    edl_path = await post_processor.detect_commercials(
                        current_path,
                        comskip_ini_path,
                        log_callback=log_callback,
                        progress_callback=comskip_progress_callback
                    )
                finally:
                    if generated_ini and comskip_ini_path:
                        try:
                            os.unlink(comskip_ini_path)
                        except FileNotFoundError:
                            pass
                        except OSError as cleanup_error:
                            logger.warning(
                                "Could not remove temporary Comskip INI %s: %s",
                                comskip_ini_path,
                                cleanup_error,
                            )
''',
    '''                from services.comskip_ini import resolved_comskip_ini

                use_custom_ini = bool(
                    getattr(settings, "comskip_use_custom_ini", False)
                )
                runtime_overrides = {}
                if getattr(settings, "comskip_dynamic_ticker_tape", False) and not use_custom_ini:
                    dimensions = await post_processor.probe_video_dimensions(
                        current_path, log_callback=log_callback
                    )
                    if dimensions:
                        width, height = dimensions
                        ticker_tape = round(height / 9)
                        runtime_overrides["ticker_tape"] = ticker_tape
                        await log_callback(f"Comskip input dimensions: {width}x{height}.")
                        await log_callback(f"Comskip resolved ticker_tape: {ticker_tape} px.")

                async with resolved_comskip_ini(
                    settings, runtime_overrides
                ) as comskip_ini_path:
                    edl_path = await post_processor.detect_commercials(
                        current_path,
                        comskip_ini_path,
                        log_callback=log_callback,
                        progress_callback=comskip_progress_callback
                    )
''',
)

replace(
    "backend/services/post_processor.py",
    "logger = logging.getLogger(__name__)\n\n\nclass OutputFormat",
    "logger = logging.getLogger(__name__)\n\n\ndef _is_no_commercials_result(returncode: int, output: str) -> bool:\n    return (\n        returncode == 1\n        and \"commercials were not found\" in output.lower()\n    )\n\n\nclass OutputFormat",
)
replace(
    "backend/services/post_processor.py",
    '''            cmd = [self._comskip_path]
            if ini_path and os.path.isfile(ini_path):
                cmd.extend(["--ini", ini_path])
''',
    '''            cmd = [self._comskip_path]
            if ini_path:
                ini_file = Path(ini_path)
                if not ini_file.is_file():
                    raise Exception(
                        f"Comskip INI file was not found at run time: {ini_path}"
                    )
                try:
                    with ini_file.open("rb") as handle:
                        handle.read(1)
                except OSError as exc:
                    raise Exception(
                        "Comskip INI file is not readable at run time: "
                        f"{ini_path}: {exc.strerror or exc}"
                    ) from exc
                cmd.extend(["--ini", str(ini_file)])
''',
)
replace(
    "backend/services/post_processor.py",
    '''            no_commercials = "commercials were not found" in combined_output.lower()
            if returncode == 1 and no_commercials:
''',
    '''            if _is_no_commercials_result(returncode, combined_output):
''',
)
replace(
    "backend/services/post_processor.py",
    '''                    if returncode == 1 and "commercials were not found" in combined_output.lower():
''',
    '''                    if _is_no_commercials_result(returncode, combined_output):
''',
)
post_processor = read("backend/services/post_processor.py")
if not post_processor.endswith("\n"):
    write("backend/services/post_processor.py", post_processor + "\n")

replace(
    "frontend/src/components/settings/ComskipSection.jsx",
    '''  comskip_connect_blocks_with_logo: 0,
  comskip_dynamic_ticker_tape: false,
  comskip_thread_count: 1,
  comskip_use_custom_ini: false,
''',
    '''  comskip_connect_blocks_with_logo: true,
  comskip_dynamic_ticker_tape: false,
  comskip_thread_count: 1,
  comskip_use_custom_ini: false,
  comskip_custom_ini_path: null,
''',
)
replace(
    "frontend/src/components/settings/ComskipSection.jsx",
    '              description="Join neighboring detected blocks when the channel logo is visible at their transition. Disabled by default because it can merge show content into a commercial break on logo-heavy channels."\n',
    '              description="Join neighboring detected blocks when the channel logo is visible at their transition. Enabled by default to match the bundled Comskip behavior; turn it off if logo-heavy channels merge show content into a break."\n',
)
replace(
    "frontend/src/components/settings/ComskipSection.jsx",
    '''                checked={Boolean(formData?.comskip_connect_blocks_with_logo)}
                onChange={(e) => onChange('comskip_connect_blocks_with_logo', e.currentTarget.checked ? 1 : 0)}
''',
    '''                checked={Boolean(
                  formData?.comskip_connect_blocks_with_logo
                    ?? COMSKIP_DEFAULTS.comskip_connect_blocks_with_logo
                )}
                onChange={(e) => onChange(
                  'comskip_connect_blocks_with_logo',
                  e.currentTarget.checked,
                )}
''',
)
replace(
    "frontend/src/components/settings/ComskipSection.jsx",
    '''          <Group>
            <Button variant="default" size="xs" disabled={managedDisabled} onClick={onResetDefaults}>
              Reset to Defaults
            </Button>
          </Group>
        </SubGroup>
      </Stack>
    </Stack>
''',
    '''        </SubGroup>
      </Stack>

      <Group>
        <Button variant="default" size="xs" disabled={!enabled} onClick={onResetDefaults}>
          Reset to Defaults
        </Button>
      </Group>
    </Stack>
''',
)

replace(
    "CHANGELOG.md",
    '''**What you would notice:** Commercial Skip has clearer explanations for every tuning control, including a warning when Comskip is configured to use more than one processing thread. A new **Dynamic ticker exclusion** option ignores roughly the bottom ninth of each recording while Comskip scans it (80 pixels for 720p and 120 pixels for 1080p), which can prevent persistent news, sports, or stock tickers from confusing detection. **Connect blocks with logo** is now managed in the UI and defaults off. Using your own `comskip.ini` is an explicit checkbox: enabling it reveals the required path and greys out Mustarrd-managed settings so it is clear that the custom file takes precedence. Saving custom mode now verifies that the path is absolute and points to a readable regular file in Mustarrd's running environment. Docker users are reminded to enter the path inside the container, where the default config directory is `/app/config`.

**What changed:** Mustarrd now builds a unique temporary Comskip INI for each recording from the persistent base file plus saved UI values and per-recording runtime overrides, then removes that file in `finally` cleanup. Dynamic ticker mode probes the recording dimensions with ffprobe and logs both the detected size and resolved `ticker_tape` value. Custom INI mode bypasses generation without discarding the saved managed values, and existing custom paths migrate to enabled custom mode. Its save-time validation now rejects relative, missing, non-file, and unreadable paths before they reach Comskip. Comskip exit code 1 is treated as a successful no-commercials result when its output says “Commercials were not found,” preventing an unnecessary TS normalization retry and false processing failure. Regression tests cover temporary-file uniqueness, override precedence, migration, custom-mode validation, and the no-commercials exit path.
''',
    '''**What you would notice:** Commercial Skip has clearer explanations for every tuning control, including a warning when Comskip is configured to use more than one processing thread. A new **Dynamic ticker exclusion** option ignores roughly the bottom ninth of each recording while Comskip scans it (80 pixels for 720p and 120 pixels for 1080p), which can prevent persistent news, sports, or stock tickers from confusing detection. **Connect blocks with logo** is now managed in the UI and follows Comskip's existing enabled default. Using your own `comskip.ini` is an explicit checkbox: enabling it reveals the required path and greys out Mustarrd-managed settings so it is clear that the custom file takes precedence. **Reset to Defaults** remains available in custom mode, returns to managed mode, and clears the custom path. Docker users are reminded to enter paths inside the container, where the default config directory is `/app/config`.

**What changed:** Mustarrd now builds a unique temporary Comskip INI for each recording under its config directory from the persistent base file plus saved UI values and per-recording runtime overrides. The generated file is removed after normal completion, failure, or cancellation. Dynamic ticker mode probes the recording dimensions with ffprobe and logs both the detected size and resolved `ticker_tape` value. Custom INI mode bypasses generation without discarding the saved managed values, and existing custom paths migrate to enabled custom mode. Custom files are validated both when Settings is saved and immediately before processing; a missing or unreadable file now fails clearly instead of silently using Comskip's built-in defaults. Comskip exit code 1 is treated as a successful no-commercials result when its output says “Commercials were not found,” preventing an unnecessary TS normalization retry and false processing failure. Regression tests cover temporary-file location, ownership and cleanup, override precedence, migration, runtime custom-path failures, Reset behavior, and no-commercials results from either output stream.
''',
)

replace(
    "docs/design/comskip-settings-editor.md",
    "107 enables black frames, logo presence, resolution change, aspect ratio changes, and silence detection.",
    "107 enables black frames, logo presence, fuzzy logic, aspect ratio changes, and silence detection.",
)
replace("docs/design/comskip-settings-editor.md", "- `8` Resolution change\n", "- `8` Fuzzy logic\n")
replace(
    "docs/design/comskip-settings-editor.md",
    "(black frames, logo, resolution change, aspect ratio, silence)",
    "(black frames, logo, fuzzy logic, aspect ratio, silence)",
)
replace(
    "docs/design/comskip-settings-editor.md",
    '''| `thread_count` | Processing threads | 1 | Number of CPU threads Comskip uses. More threads = faster processing but more CPU load during recording. Maximum: 16. | Clamped to 1..16 (enforced in backend validation and as `min=1, max=16` on the NumberInput). |

---
''',
    '''| `thread_count` | Processing threads | 1 | Number of CPU threads Comskip uses. More threads can change detection results as well as increase CPU load. Maximum: 16. | Clamped to 1..16 (enforced in backend validation and as `min=1, max=16` on the NumberInput). |

### Advanced

| Field | Label | Default | Tooltip |
|-------|-------|---------|---------|
| `connect_blocks_with_logo` | Connect blocks with logo | true | Join neighboring detected blocks when the channel logo remains visible at their transition. Enabled by default to match the bundled Comskip configuration; disable it on logo-heavy channels if show content is merged into a break. |
| `dynamic_ticker_tape` | Dynamic ticker exclusion | false | Before each managed scan, probe the selected video height and ignore roughly the bottom ninth of the picture. Custom INI mode bypasses this runtime override. |

---
''',
)
replace(
    "docs/design/comskip-settings-editor.md",
    '"Reset to Defaults" restores all Comskip fields to the values in the table above without saving, leaving the user a chance to review before clicking Save.\n',
    '"Reset to Defaults" remains available while custom INI mode is active. It restores every managed Comskip field, disables custom mode, clears `comskip_custom_ini_path`, and leaves the changes unsaved so the user can review them before clicking Save.\n',
)
replace_regex(
    "docs/design/comskip-settings-editor.md",
    r"## comskip\.ini path handling\n\n.*?\n---\n\n## Backend changes needed",
    '''## comskip.ini path handling

The legacy `comskip_ini_path` field remains backend-managed and may be auto-filled with the config-directory base file. It is not the custom-mode selector and never overrides managed generation.

- `comskip_use_custom_ini` is the authoritative mode switch.
- `comskip_custom_ini_path` is required only while custom mode is enabled. Existing non-default legacy custom paths migrate into this field and enable custom mode.
- Custom paths are normalized and validated when Settings is saved, then validated again at run time. If the file moved, its mount disappeared, or it became unreadable, Commercial Skip fails with a clear error instead of silently using Comskip defaults.
- Managed mode writes a unique temporary INI in Mustarrd's config directory, applies saved settings, then applies per-recording runtime overrides. Resolution returns both the path and whether Mustarrd owns the file so custom and legacy files are never deleted.
- Generated files are removed after normal completion, failure, or cancellation. A file left by abrupt process termination remains visible in the config directory rather than an unrelated system temp directory.

---

## Backend changes needed''',
)
replace(
    "docs/design/comskip-settings-editor.md",
    '''3. **`api/settings.py`**: include all new fields in GET/PUT. Validate `min <= max` pairs and clamp `thread_count` to 1..16 before saving. Remove the auto-fill logic for `comskip_ini_path` (or guard it so it only applies when `comskip_custom_ini_path` is null and `comskip_use_generated_ini` is false).
4. **`services/post_processor.py`**: when running Comskip, honor enabled custom mode first. Otherwise, write a per-run temporary `comskip.ini` from the stored and runtime settings.
''',
    '''3. **`api/settings.py`**: include all new fields in GET/PUT. Validate `min <= max` pairs, clamp `thread_count` to 1..16, and validate enabled custom paths through the shared service validator before saving.
4. **`services/comskip_ini.py` / `services/post_processor.py`**: resolve explicit custom mode first and fail closed when its file is unavailable. Otherwise, write an owned per-run temporary INI in the config directory and clean it after use. Recheck any explicit INI immediately before each Comskip process starts.
''',
)
replace(
    "docs/design/comskip-settings-editor.md",
    '''   - "Reset to Defaults" button that calls `setFormData(prev => ({ ...prev, ...COMSKIP_DEFAULTS }))`.
   - A custom-INI checkbox with a required path field; gray out managed controls while it is enabled.
''',
    '''   - "Reset to Defaults" button that stays available in custom mode, applies `COMSKIP_DEFAULTS`, disables custom mode, and clears the custom path.
   - A custom-INI checkbox with a required path field; gray out managed controls while it is enabled.
   - Boolean controls for dynamic ticker exclusion and connecting logo blocks, with the latter defaulting true to match the bundled base.
''',
)

write(
    "backend/tests/test_comskip_ini_generation.py",
    '''"""Tests for generated and custom Comskip INI resolution."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from models import AppSettings
from services.comskip_ini import (
    ComskipIniError,
    generate_comskip_ini,
    render_comskip_ini,
    resolve_comskip_ini,
    resolved_comskip_ini,
    tunable_overrides,
)


class RenderComskipIniTests(unittest.TestCase):
    def test_replaces_existing_key_and_drops_inline_comment(self):
        base = "detect_method=255\\t\\t;1=black frame, 2=logo\\noutput_edl=1\\n"
        result = render_comskip_ini(base, {"detect_method": 107})
        self.assertIn("detect_method=107", result.splitlines())
        self.assertNotIn("255", result)

    def test_preserves_unrelated_lines(self):
        base = "output_edl=1\\nmax_volume=500\\t; comment\\n"
        result = render_comskip_ini(base, {"detect_method": 107})
        lines = result.splitlines()
        self.assertIn("output_edl=1", lines)
        self.assertIn("max_volume=500\\t; comment", lines)

    def test_appends_missing_keys(self):
        base = "output_edl=1\\n"
        result = render_comskip_ini(base, {"thread_count": 4, "remove_after": 2})
        lines = result.splitlines()
        self.assertIn("thread_count=4", lines)
        self.assertIn("remove_after=2", lines)
        self.assertIn("output_edl=1", lines)

    def test_commented_out_key_is_not_treated_as_assignment(self):
        base = "; detect_method=99 old note\\noutput_edl=1\\n"
        result = render_comskip_ini(base, {"detect_method": 107})
        lines = result.splitlines()
        self.assertIn("; detect_method=99 old note", lines)
        self.assertIn("detect_method=107", lines)

    def test_tunable_overrides_reads_model_defaults(self):
        overrides = tunable_overrides(AppSettings(
            comskip_detect_method=107,
            comskip_max_commercialbreak=600,
            comskip_min_commercialbreak=25,
            comskip_max_commercial_size=125,
            comskip_min_commercial_size=4,
            comskip_always_keep_first_seconds=0,
            comskip_always_keep_last_seconds=60,
            comskip_remove_before=0,
            comskip_remove_after=0,
            comskip_connect_blocks_with_logo=True,
            comskip_thread_count=1,
        ))
        self.assertEqual(overrides, {
            "detect_method": 107,
            "max_commercialbreak": 600,
            "min_commercialbreak": 25,
            "max_commercial_size": 125,
            "min_commercial_size": 4,
            "always_keep_first_seconds": 0,
            "always_keep_last_seconds": 60,
            "remove_before": 0,
            "remove_after": 0,
            "connect_blocks_with_logo": 1,
            "thread_count": 1,
        })

    def test_unset_tunables_are_skipped(self):
        settings = AppSettings()
        settings.comskip_detect_method = None
        settings.comskip_thread_count = 8
        overrides = tunable_overrides(settings)
        self.assertNotIn("detect_method", overrides)
        self.assertEqual(overrides["thread_count"], 8)


class GenerateAndResolveTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.config_dir = Path(self._tmp.name)
        (self.config_dir / "comskip.ini").write_text(
            "detect_method=255\\nconnect_blocks_with_logo=1\\noutput_edl=1\\n",
            encoding="utf-8",
        )
        self.settings = AppSettings(
            comskip_detect_method=107,
            comskip_connect_blocks_with_logo=True,
            comskip_thread_count=2,
        )

    def tearDown(self):
        self._tmp.cleanup()

    def _patch_config(self):
        return patch("services.comskip_ini.ensure_config_files", return_value=self.config_dir)

    def test_generate_writes_unique_temporary_ini_in_config_dir(self):
        with self._patch_config():
            path = generate_comskip_ini(self.settings)
            second_path = generate_comskip_ini(self.settings)
        try:
            self.assertNotEqual(path, second_path)
            self.assertEqual(Path(path).parent, self.config_dir)
            self.assertEqual(Path(second_path).parent, self.config_dir)
            self.assertTrue(Path(path).name.startswith(".mustarrd-comskip-"))
            content = Path(path).read_text(encoding="utf-8")
            self.assertIn("detect_method=107", content.splitlines())
            self.assertIn("thread_count=2", content.splitlines())
            self.assertIn("output_edl=1", content.splitlines())
        finally:
            Path(path).unlink(missing_ok=True)
            Path(second_path).unlink(missing_ok=True)

    def test_runtime_overrides_take_precedence(self):
        with self._patch_config():
            path = generate_comskip_ini(self.settings, {"ticker_tape": 120})
        try:
            self.assertIn("ticker_tape=120", Path(path).read_text().splitlines())
        finally:
            Path(path).unlink(missing_ok=True)

    def test_enabled_logo_default_matches_bundled_base(self):
        with self._patch_config():
            path = generate_comskip_ini(self.settings)
        try:
            self.assertIn("connect_blocks_with_logo=1", Path(path).read_text().splitlines())
        finally:
            Path(path).unlink(missing_ok=True)

    def test_user_can_disable_logo_block_connection(self):
        self.settings.comskip_connect_blocks_with_logo = False
        with self._patch_config():
            path = generate_comskip_ini(self.settings)
        try:
            self.assertIn("connect_blocks_with_logo=0", Path(path).read_text().splitlines())
        finally:
            Path(path).unlink(missing_ok=True)

    def test_generate_falls_back_to_minimal_base_with_edl(self):
        (self.config_dir / "comskip.ini").unlink()
        with self._patch_config(), patch(
            "services.comskip_ini._resolve_bundled_comskip_ini", return_value=None
        ):
            path = generate_comskip_ini(self.settings)
        try:
            content = Path(path).read_text(encoding="utf-8")
            self.assertIn("output_edl=1", content.splitlines())
            self.assertIn("detect_method=107", content.splitlines())
        finally:
            Path(path).unlink(missing_ok=True)

    def test_resolve_prefers_valid_custom_ini_and_skips_generation(self):
        custom_path = self.config_dir / "custom.ini"
        custom_path.write_text("output_edl=1\\n", encoding="utf-8")
        self.settings.comskip_use_custom_ini = True
        self.settings.comskip_custom_ini_path = str(custom_path)
        with patch("services.comskip_ini.generate_comskip_ini") as mock_generate:
            result, is_temporary = resolve_comskip_ini(self.settings)
        self.assertEqual(result, str(custom_path.absolute()))
        self.assertFalse(is_temporary)
        mock_generate.assert_not_called()

    def test_resolve_custom_mode_fails_closed_when_file_moves(self):
        self.settings.comskip_use_custom_ini = True
        self.settings.comskip_custom_ini_path = str(self.config_dir / "missing.ini")
        with patch("services.comskip_ini.generate_comskip_ini") as mock_generate:
            with self.assertRaisesRegex(ComskipIniError, "not found"):
                resolve_comskip_ini(self.settings)
        mock_generate.assert_not_called()

    def test_resolve_custom_mode_requires_path(self):
        self.settings.comskip_use_custom_ini = True
        self.settings.comskip_custom_ini_path = "   "
        with self.assertRaisesRegex(ComskipIniError, "required"):
            resolve_comskip_ini(self.settings)

    def test_resolve_ignores_saved_custom_path_when_custom_mode_is_off(self):
        self.settings.comskip_use_custom_ini = False
        self.settings.comskip_custom_ini_path = "/custom/comskip.ini"
        with self._patch_config():
            result, is_temporary = resolve_comskip_ini(self.settings)
        try:
            self.assertTrue(Path(result).name.startswith(".mustarrd-comskip-"))
            self.assertTrue(is_temporary)
        finally:
            Path(result).unlink(missing_ok=True)

    def test_resolve_falls_back_to_legacy_path_without_ownership(self):
        self.settings.comskip_custom_ini_path = None
        self.settings.comskip_ini_path = "/legacy/comskip.ini"
        with patch("services.comskip_ini.generate_comskip_ini", return_value=None):
            result, is_temporary = resolve_comskip_ini(self.settings)
        self.assertEqual(result, "/legacy/comskip.ini")
        self.assertFalse(is_temporary)


class ResolvedIniLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addAsyncCleanup(self._cleanup_tempdir)
        self.config_dir = Path(self._tmp.name)
        (self.config_dir / "comskip.ini").write_text(
            "output_edl=1\\nconnect_blocks_with_logo=1\\n", encoding="utf-8"
        )
        self.settings = AppSettings(comskip_connect_blocks_with_logo=True)

    async def _cleanup_tempdir(self):
        self._tmp.cleanup()

    def _patch_config(self):
        return patch("services.comskip_ini.ensure_config_files", return_value=self.config_dir)

    async def test_generated_ini_removed_after_success(self):
        with self._patch_config():
            async with resolved_comskip_ini(self.settings) as path:
                generated = Path(path)
                self.assertTrue(generated.exists())
        self.assertFalse(generated.exists())

    async def test_generated_ini_removed_after_failure(self):
        generated = None
        with self._patch_config():
            with self.assertRaisesRegex(RuntimeError, "boom"):
                async with resolved_comskip_ini(self.settings) as path:
                    generated = Path(path)
                    raise RuntimeError("boom")
        self.assertIsNotNone(generated)
        self.assertFalse(generated.exists())

    async def test_custom_ini_is_never_deleted(self):
        custom = self.config_dir / "custom.ini"
        custom.write_text("output_edl=1\\n", encoding="utf-8")
        self.settings.comskip_use_custom_ini = True
        self.settings.comskip_custom_ini_path = str(custom)
        async with resolved_comskip_ini(self.settings) as path:
            self.assertEqual(Path(path), custom)
        self.assertTrue(custom.exists())


if __name__ == "__main__":
    unittest.main()
''',
)

replace(
    "backend/tests/test_comskip_tunables_api.py",
    '        self.assertEqual(result["comskip_connect_blocks_with_logo"], 0)\n',
    '        self.assertTrue(result["comskip_connect_blocks_with_logo"])\n',
)
replace(
    "backend/tests/test_comskip_probe_sidecar_cleanup.py",
    "    async def test_exit_one_no_commercials_does_not_normalize_ts(self):\n",
    '''    async def test_missing_ini_fails_before_comskip_is_spawned(self):
        ts_path = Path(self.tmp) / "Show.ts"
        ts_path.write_bytes(b"\\x47" * 188)
        missing_ini = Path(self.tmp) / "missing.ini"
        processor = PostProcessor()
        processor._comskip_path = "/usr/bin/comskip"

        create_process = AsyncMock()
        with patch.object(
            type(processor), "comskip_available",
            new_callable=PropertyMock, return_value=True,
        ), patch(
            "asyncio.create_subprocess_exec", new=create_process,
        ):
            with self.assertRaisesRegex(Exception, "not found at run time"):
                await processor.detect_commercials(
                    str(ts_path), ini_path=str(missing_ini)
                )

        create_process.assert_not_awaited()

    async def test_exit_one_no_commercials_does_not_normalize_ts(self):
''',
)

replace(
    "frontend/src/components/settings/ComskipSection.test.jsx",
    '''    expect(screen.getByRole('checkbox', { name: 'Black frames' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Reset to Defaults' })).toBeDisabled()
    expect(screen.getByText(/Custom INI mode is active/)).toBeInTheDocument()
''',
    '''    expect(screen.getByRole('checkbox', { name: 'Black frames' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Reset to Defaults' })).toBeEnabled()
    expect(screen.getByText(/Custom INI mode is active/)).toBeInTheDocument()
''',
)
replace(
    "frontend/src/components/settings/ComskipSection.test.jsx",
    "  it('warns that multiple processing threads can change detection', () => {\n",
    '''  it('resets from custom mode', () => {
    const { onResetDefaults } = renderSection({
      comskip_use_custom_ini: true,
      comskip_custom_ini_path: '/tmp/custom.ini',
    })

    fireEvent.click(screen.getByRole('button', { name: 'Reset to Defaults' }))

    expect(onResetDefaults).toHaveBeenCalledOnce()
  })

  it('uses a boolean enabled default for connecting logo blocks', () => {
    const { onChange } = renderSection()
    const checkbox = screen.getByRole('checkbox', { name: 'Connect blocks with logo' })

    expect(checkbox).toBeChecked()
    fireEvent.click(checkbox)

    expect(onChange).toHaveBeenCalledWith('comskip_connect_blocks_with_logo', false)
  })

  it('warns that multiple processing threads can change detection', () => {
''',
)
replace(
    "frontend/src/pages/Settings.test.jsx",
    "  comskip_connect_blocks_with_logo: 0,\n",
    "  comskip_connect_blocks_with_logo: true,\n",
)
replace(
    "frontend/src/pages/Settings.test.jsx",
    "  it('offers a GPU device picker listing every detected render node', async () => {\n",
    '''  it('resets custom Comskip mode and clears its path', async () => {
    settingsApi.get.mockResolvedValue({
      ...baseSettings,
      comskip_enabled: true,
      comskip_use_custom_ini: true,
      comskip_custom_ini_path: '/app/config/custom-comskip.ini',
      comskip_connect_blocks_with_logo: false,
    })

    renderSettings()
    await screen.findByText('Connections')
    fireEvent.click(screen.getByText('Commercial Skip'))

    const reset = await screen.findByRole('button', { name: 'Reset to Defaults' })
    expect(reset).toBeEnabled()
    fireEvent.click(reset)

    expect(screen.queryByPlaceholderText('/path/to/comskip.ini')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Save Changes' }))

    await waitFor(() => {
      expect(settingsApi.update).toHaveBeenCalled()
    })
    expect(settingsApi.update.mock.calls[0][0]).toMatchObject({
      comskip_use_custom_ini: false,
      comskip_custom_ini_path: null,
      comskip_connect_blocks_with_logo: true,
      comskip_dynamic_ticker_tape: false,
      comskip_thread_count: 1,
    })
  })

  it('offers a GPU device picker listing every detected render node', async () => {
''',
)

for path in (
    "docs/design/comskip-settings-editor.md",
    "frontend/src/components/settings/ComskipSection.jsx",
    "CHANGELOG.md",
):
    if "Resolution change" in read(path):
        raise RuntimeError(f"{path}: stale detect-bit label remains")

print("Applied PR #420 maintainer review fixes.")
