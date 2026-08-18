#!/usr/bin/env python3
import os
import subprocess
import sys
from pathlib import Path

REPAIRS = {
    "automation/repair-pr405": {
        "original": "e5e3bef1c77b5dc643e23175afa6af5e436960ba",
        "target": "agent/vaapi-render-device-env",
        "message": "Sync VA-API branch with upstream",
    },
    "automation/repair-pr407": {
        "original": "6dba68be7b3395d57e0ad2ff71bcf5de56d7c9df",
        "target": "agent/template-subdirectories",
        "message": "Address template path review feedback",
    },
}


def run(*args, check=True):
    return subprocess.run(args, check=check, text=True, capture_output=not check)


def git(*args, check=True):
    return run("git", *args, check=check)


def replace_once(path: Path, old: str, new: str):
    text = path.read_text()
    if old not in text:
        raise RuntimeError(f"Expected text not found in {path}: {old!r}")
    path.write_text(text.replace(old, new, 1))


def insert_after(text: str, marker: str, insertion: str) -> str:
    if marker not in text:
        raise RuntimeError(f"Marker not found: {marker!r}")
    pos = text.index(marker) + len(marker)
    return text[:pos] + insertion + text[pos:]


def merge_upstream():
    result = subprocess.run(
        ["git", "merge", "--no-ff", "--no-commit", "upstream/main"],
        text=True,
        capture_output=True,
    )
    if result.returncode == 0:
        return
    conflicts = git("diff", "--name-only", "--diff-filter=U").stdout.strip().splitlines()
    if conflicts != ["CHANGELOG.md"]:
        raise RuntimeError(f"Unexpected merge conflicts: {conflicts}\n{result.stdout}\n{result.stderr}")
    git("checkout", "--theirs", "CHANGELOG.md")
    git("add", "CHANGELOG.md")


def repair_405():
    changelog = Path("CHANGELOG.md")
    text = changelog.read_text()
    title = "### Improved: VA-API can use a non-default render device"
    if title not in text:
        entry = """### Improved: VA-API can use a non-default render device

**What you would notice:** If your Intel or AMD GPU is exposed as a DRM render node other than `/dev/dri/renderD128` (for example `/dev/dri/renderD129`), you can now point Mustarrd at that device with `CATCHUP_VAAPI_RENDER_DEVICE`. Docker startup permissions follow the same device, and Unraid users can set it from the advanced container settings. Existing setups keep using `/dev/dri/renderD128` by default.

**What changed:** Mustarrd now reads `CATCHUP_VAAPI_RENDER_DEVICE` for VA-API diagnostics and every FFmpeg hardware-encode path, with blank values falling back to `/dev/dri/renderD128`. Docker startup uses the same configured render node when assigning GPU permissions, and the setting is documented for Docker Compose and Unraid.

"""
        text = insert_after(text, "## 2026-08-15\n\n", entry)
        changelog.write_text(text)
        git("add", "CHANGELOG.md")


def repair_407():
    for filename in (
        "frontend/src/components/DownloadModal.jsx",
        "frontend/src/components/ScheduleModal.jsx",
    ):
        replace_once(
            Path(filename),
            "setFilename(data.filename.replace('.ts', ''))",
            r"setFilename(data.filename.replace(/\.ts$/, ''))",
        )

    primitives = Path("frontend/src/components/settings/SettingsPrimitives.jsx")
    text = primitives.read_text()
    text = text.replace(
        "import { Box, Divider, Group, Stack, Text, Tooltip } from '@mantine/core'",
        "import { Alert, Box, Code, Divider, Group, Stack, Text, Tooltip } from '@mantine/core'",
        1,
    ).replace(
        "import { IconInfoCircle } from '@tabler/icons-react'",
        "import { IconAlertCircle, IconInfoCircle } from '@tabler/icons-react'",
        1,
    )
    anchor = """      {description && <Text size=\"sm\" c=\"dimmed\">{description}</Text>}
    </Stack>"""
    hint = """      {description && <Text size=\"sm\" c=\"dimmed\">{description}</Text>}
      {title === 'File Naming' && (
        <Alert color=\"blue\" variant=\"light\" icon={<IconAlertCircle size={16} />} mt=\"sm\">
          A forward slash in a template creates a folder. For example{' '}
          <Code>{'TV Shows/{show}/Season {season:02d}/{show} - S{season:02d}E{episode:02d}'}</Code> files the
          recording into nested folders inside your completed folder. Slashes that come from the guide itself
          (a show called &quot;AC/DC&quot;, say) stay part of the name and don&apos;t create folders.
        </Alert>
      )}
    </Stack>"""
    if anchor not in text:
        raise RuntimeError("SectionHeader anchor not found")
    primitives.write_text(text.replace(anchor, hint, 1))

    changelog = Path("CHANGELOG.md")
    text = changelog.read_text()
    title = "### Changed: Filename templates can create folders"
    if title not in text:
        entry = """## 2026-08-17

### Changed: Filename templates can create folders

**What you would notice:** A forward slash (`/`) in a recording filename template now creates a real subfolder inside your recording folders instead of being flattened into a space. For example, `TV Shows/{show}/Season {season:02d}/{show} - S{season:02d}E{episode:02d}` files an episode under its show and season automatically. This is a behavior change for any existing template that already contains `/`: after upgrading, those slashes create folders. Slashes that come from guide metadata, such as a show named `AC/DC`, are still sanitized as part of that name and do not create extra levels. Edited filenames in the Download and Schedule dialogs preserve the same safe relative hierarchy.

**What changed:** Template rendering now splits only literal slashes from the saved template, formats and sanitizes each path component independently, and keeps the result relative to the configured recording folder. Client-supplied recording names use the same component-by-component sanitizer, so absolute paths and `..` traversal cannot escape the recording root. Scheduled recordings and completed-folder moves preserve the generated hierarchy. The Download and Schedule dialogs also strip only the final `.ts` suffix from filename previews, so a folder whose name contains `.ts` is not mangled or given a double extension.

---

"""
        text = insert_after(text, "---\n\n", entry)
        changelog.write_text(text)

    git("add", "-A")


def prepare(head_ref: str):
    cfg = REPAIRS[head_ref]
    git("config", "user.name", "matrix2669")
    git("config", "user.email", "jarred@jdscomputing.com")
    subprocess.run(["git", "remote", "remove", "upstream"], check=False)
    git("remote", "add", "upstream", "https://github.com/razzamatazm/mustarrd.git")
    git("fetch", "origin", cfg["target"])
    git("fetch", "upstream", "main")
    git("reset", "--hard", cfg["original"])
    merge_upstream()
    if head_ref.endswith("405"):
        repair_405()
    else:
        repair_407()
    git("add", "-A")
    git("diff", "--check")
    Path("/tmp/mustarrd-repair-target").write_text(cfg["target"])
    Path("/tmp/mustarrd-repair-original").write_text(cfg["original"])
    Path("/tmp/mustarrd-repair-message").write_text(cfg["message"])


def publish(head_ref: str):
    cfg = REPAIRS[head_ref]
    git("add", "-A")
    git("commit", "-m", cfg["message"])
    git(
        "push",
        "origin",
        f"HEAD:refs/heads/{cfg['target']}",
        f"--force-with-lease=refs/heads/{cfg['target']}:{cfg['original']}",
    )


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in {"prepare", "publish"}:
        raise SystemExit("usage: repair_pr_branch.py prepare|publish <automation-branch>")
    action, head_ref = sys.argv[1:]
    if head_ref not in REPAIRS:
        raise SystemExit(f"unsupported repair branch: {head_ref}")
    (prepare if action == "prepare" else publish)(head_ref)


if __name__ == "__main__":
    main()
