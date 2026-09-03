# Design: Comskip Settings Editor

**Status:** Proposed  
**Requested by:** Tyler (2026-06-06)  
**Branch:** design/comskip-settings-editor

---

## What we are building

A new "Comskip" section in the Settings page that lets users tune how Comskip detects commercials, with a tooltip on each label explaining the setting and its recommended value, and a "Reset to Defaults" button.

---

## Where it lives

New entry in `ADMIN_SECTIONS` in `Settings.jsx`, inserted after "Post-Processing":

```
Accounts | Users | Plex Integration | Recording | Post-Processing | Comskip | File Naming | Appearance | Security | Logs
```

Icon: `IconScissors` (not `IconAdjustments`). The section is about cutting commercials out of recordings.

---

## When Comskip is disabled

Display the section but grey out all controls and show a banner:

```
┌────────────────────────────────────────────────────────────────┐
│  ⓘ  Comskip is not enabled. Turn it on in Post-Processing      │
│     to configure these settings.                               │
└────────────────────────────────────────────────────────────────┘
```

This lets users pre-configure settings before enabling Comskip.

---

## Settings to expose

Settings are stored in `app_settings`. Comskip receives them via a unique, per-run temporary `comskip.ini`; runtime values such as dynamic ticker exclusion override saved UI values, and the file is removed after Comskip exits.

### Commercial Detection

| Field | Label | Default | Tooltip |
|-------|-------|---------|---------|
| `detect_method` | Detection methods | 107 | Which signals Comskip looks for when finding commercial boundaries. 107 enables black frames, logo presence, fuzzy logic, aspect ratio changes, and silence detection. Recommended: 107. Higher values add rarely-useful signals and slow processing. |

`detect_method` is a bitmask. UI: a `CheckboxGroup` (visible checkboxes, not a dropdown) with human labels:

- `1` Black frames
- `2` Logo detection
- `4` Scene change
- `8` Fuzzy logic
- `32` Aspect ratio change
- `64` Silence detection

Default `detect_method = 107` pre-checks: 1, 2, 8, 32, 64 (black frames, logo, fuzzy logic, aspect ratio, silence). Scene change (4) is **not** included in 107 and must not be pre-checked.

(Values 16 = closed captions and 128 = cutscenes omitted: rarely available or effective on IPTV streams.)

### Commercial Timing

| Field | Label | Default | Tooltip | Validation |
|-------|-------|---------|---------|------------|
| `max_commercialbreak` | Max commercial break (seconds) | 600 | Longest stretch of continuous commercials Comskip will mark as a single break. Increase if your provider runs long ad blocks. | Must be >= `min_commercialbreak`. |
| `min_commercialbreak` | Min commercial break (seconds) | 25 | Shortest stretch Comskip will call a commercial break. Lower values may cause false positives on short scene transitions. | Must be <= `max_commercialbreak`. |
| `max_commercial_size` | Max single commercial (seconds) | 125 | Longest a single commercial can be. Spots longer than this are treated as show content. | Must be >= `min_commercial_size`. |
| `min_commercial_size` | Min single commercial (seconds) | 4 | Shortest a single commercial can be. Raise this to avoid false cuts on brief logo bumpers. | Must be <= `max_commercial_size`. |

Save Settings is disabled (with an inline error message) if `min_commercialbreak > max_commercialbreak` or `min_commercial_size > max_commercial_size`.

### Show Protection

| Field | Label | Default | Tooltip | Validation |
|-------|-------|---------|---------|------------|
| `always_keep_first_seconds` | Always keep first N seconds | 0 | Never mark this many seconds at the start of the recording as commercial, regardless of what Comskip detects. Useful for providers that play a logo intro before the show. | |
| `always_keep_last_seconds` | Always keep last N seconds | 60 | Never mark this many seconds at the end of the recording as commercial. Prevents accidental cutting of end credits or a post-credits scene. | |
| `remove_before` | Remove N seconds before each break | 0 | Extra seconds of show content to cut immediately before each detected commercial block. Use with caution: removes show content. | |
| `remove_after` | Remove N seconds after each break | 0 | Extra seconds of show content to cut immediately after each detected commercial block. | |
| `thread_count` | Processing threads | 1 | Number of CPU threads Comskip uses. More threads can change detection results as well as increase CPU load. Maximum: 16. | Clamped to 1..16 (enforced in backend validation and as `min=1, max=16` on the NumberInput). |

### Advanced

| Field | Label | Default | Tooltip |
|-------|-------|---------|---------|
| `connect_blocks_with_logo` | Connect blocks with logo | true | Join neighboring detected blocks when the channel logo remains visible at their transition. Enabled by default to match the bundled Comskip configuration; disable it on logo-heavy channels if show content is merged into a break. |
| `dynamic_ticker_tape` | Dynamic ticker exclusion | false | Before each managed scan, probe the selected video height and ignore roughly the bottom ninth of the picture. Custom INI mode bypasses this runtime override. |

---

## Reset to Defaults button

Appears at the bottom of the section, alongside the existing Save Settings button:

```
[Reset to Defaults]   [Save Settings]
```

"Reset to Defaults" remains available while custom INI mode is active. It restores every managed Comskip field, disables custom mode, clears `comskip_custom_ini_path`, and leaves the changes unsaved so the user can review them before clicking Save.

---

## comskip.ini path handling

The legacy `comskip_ini_path` field remains backend-managed and may be auto-filled with the config-directory base file. It is not the custom-mode selector and never overrides managed generation.

- `comskip_use_custom_ini` is the authoritative mode switch.
- `comskip_custom_ini_path` is required only while custom mode is enabled. Existing non-default legacy custom paths migrate into this field and enable custom mode.
- Custom paths are normalized and validated when Settings is saved, then validated again at run time. If the file moved, its mount disappeared, or it became unreadable, Commercial Skip fails with a clear error instead of silently using Comskip defaults.
- Managed mode writes a unique temporary INI in Mustarrd's config directory, applies saved settings, then applies per-recording runtime overrides. Resolution returns both the path and whether Mustarrd owns the file so custom and legacy files are never deleted.
- Generated files are removed after normal completion, failure, or cancellation. A file left by abrupt process termination remains visible in the config directory rather than an unrelated system temp directory.

---

## Backend changes needed

1. **`models/settings.py`**: add the managed Comskip fields plus `comskip_use_custom_ini` and nullable `comskip_custom_ini_path` fields.
2. **`backend/database.py`**: `ALTER TABLE` migration for all new columns on startup.
3. **`api/settings.py`**: include all new fields in GET/PUT. Validate `min <= max` pairs, clamp `thread_count` to 1..16, and validate enabled custom paths through the shared service validator before saving.
4. **`services/comskip_ini.py` / `services/post_processor.py`**: resolve explicit custom mode first and fail closed when its file is unavailable. Otherwise, write an owned per-run temporary INI in the config directory and clean it after use. Recheck any explicit INI immediately before each Comskip process starts.

---

## Frontend changes needed

1. **`Settings.jsx`**: add `{ id: 'comskip', label: 'Comskip', icon: IconScissors }` to `ADMIN_SECTIONS`.
2. New `ComskipSection` component in `frontend/src/components/settings/ComskipSection.jsx`:
   - Disabled banner when `formData.comskip_enabled` is false (controls greyed, not hidden).
   - Three subsections with `NumberInput` fields (timing + show protection) and a `CheckboxGroup` for `detect_method`.
   - Tooltips via Mantine `Tooltip` on each label.
   - Inline validation errors if `min_commercialbreak > max_commercialbreak` or `min_commercial_size > max_commercial_size`.
   - "Reset to Defaults" button that stays available in custom mode, applies `COMSKIP_DEFAULTS`, disables custom mode, and clears the custom path.
   - A custom-INI checkbox with a required path field; gray out managed controls while it is enabled.
   - Boolean controls for dynamic ticker exclusion and connecting logo blocks, with the latter defaulting true to match the bundled base.
