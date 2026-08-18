#!/usr/bin/env python3
import subprocess
import sys
from pathlib import Path

UPSTREAM = "df494fe35bc25b93a08b736226e77210b38c83a2"
TARGET = "agent/structured-epg-filename-templates"


def run(*args, check=True):
    p = subprocess.run(args, text=True, capture_output=True)
    if check and p.returncode:
        raise RuntimeError(f"command failed: {' '.join(args)}\n{p.stdout}\n{p.stderr}")
    return p


def git(*args, check=True):
    return run("git", *args, check=check)


def prepare():
    git("config", "user.name", "matrix2669")
    git("config", "user.email", "jarred@jdscomputing.com")
    subprocess.run(["git", "remote", "remove", "upstream"], check=False)
    git("remote", "add", "upstream", "https://github.com/razzamatazm/mustarrd.git")
    git("fetch", "upstream", "main")
    actual = git("rev-parse", "upstream/main").stdout.strip()
    if actual != UPSTREAM:
        raise RuntimeError(f"upstream moved: expected {UPSTREAM}, got {actual}")
    git("reset", "--hard", UPSTREAM)
    Path("backend/tests/test_structured_filename_templates.py").write_text(
        Path("/tmp/pr408-test_structured_filename_templates.py").read_text()
    )

    namer = Path("backend/services/file_namer.py")
    text = namer.read_text()
    start = text.index("    def generate_filename(\n")
    end = text.index("\n\n# Global instance", start)
    replacement = '''    @staticmethod
    def _tmdb_hint(value) -> str:
        raw = str(value or "").strip()
        match = re.fullmatch(r"(?:(?:series|movie)/)?(\\d+)", raw, re.IGNORECASE)
        if not match:
            return ""
        tmdb_id = match.group(1)
        return f"{{tmdb-{tmdb_id}}} [tmdbid-{tmdb_id}]"

    @staticmethod
    def _xmltv_season_is_unknown(value) -> bool:
        raw = str(value or "").strip()
        if not raw:
            return False
        try:
            return int(raw.split(".", 1)[0]) == -1
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _coerce_optional_int(value) -> Optional[int]:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _trim_empty_title_separator(value: str) -> str:
        # A common custom TV template ends in " - {title}". Structured guide
        # rows do not always carry a subtitle, so remove only a dangling final
        # separator rather than falling back to a different template.
        return re.sub(r"\\s*[-–—:|]\\s*$", "", value).strip()

    def generate_filename(
        self,
        program: dict,
        channel: dict,
        program_type: str,
        settings: dict = None
    ) -> str:
        title = program.get("title", "Unknown")
        description = program.get("description", "")
        start_time_str = program.get("start_time")
        channel_name = channel.get("name", "")

        if start_time_str:
            try:
                start_time = datetime.fromisoformat(start_time_str)
            except (ValueError, TypeError):
                start_time = datetime.utcnow()
        else:
            start_time = datetime.utcnow()

        date_str = start_time.strftime("%Y-%m-%d")
        s = settings or {}
        tmdb_hint = self._tmdb_hint(program.get("tmdb_id"))

        if program_type == "tv_show":
            structured_season = self._coerce_optional_int(program.get("season_number"))
            structured_episode = self._coerce_optional_int(program.get("episode_number"))
            full_text = f"{title} {description}"
            parsed_season_ep = self.extract_season_episode(full_text)

            if structured_season is not None and structured_episode is not None:
                season, episode = structured_season, structured_episode
                if season == 0 and self._xmltv_season_is_unknown(program.get("episode_xmltv_ns")):
                    season = start_time.year
                show_name = self.extract_show_name(title) if self.extract_season_episode(title) else title
                episode_title = (program.get("subtitle") or self.extract_episode_title(title) or "").strip()
                context = {
                    "show": show_name,
                    "season": season,
                    "episode": episode,
                    "title": episode_title,
                    "date": date_str,
                    "channel": channel_name,
                    "tmdb": tmdb_hint,
                }
                custom = s.get("tv_template")
                if custom:
                    template = custom
                elif episode_title:
                    template = self._DEFAULT_TEMPLATES["tv"]
                else:
                    template = self._DEFAULT_TEMPLATES["tv_no_subtitle"]
            elif parsed_season_ep:
                show_name = self.extract_show_name(title)
                episode_title = self.extract_episode_title(title)
                context = {
                    "show": show_name,
                    "season": parsed_season_ep[0],
                    "episode": parsed_season_ep[1],
                    "title": episode_title,
                    "date": date_str,
                    "channel": channel_name,
                    "tmdb": tmdb_hint,
                }
                custom = s.get("tv_template")
                if custom:
                    template = custom
                elif episode_title:
                    template = self._DEFAULT_TEMPLATES["tv"]
                else:
                    template = self._DEFAULT_TEMPLATES["tv_no_subtitle"]
            else:
                context = {"title": title, "date": date_str, "channel": channel_name, "tmdb": tmdb_hint}
                template = s.get("default_template") or self._DEFAULT_TEMPLATES["default"]
        elif program_type == "sports":
            context = {"title": title, "date": date_str, "channel": channel_name, "tmdb": tmdb_hint}
            template = s.get("sports_template") or self._DEFAULT_TEMPLATES["sports"]
        elif program_type == "movie":
            year = self.extract_year(description) or self.extract_year(title) or start_time.year
            clean_title = re.sub(r'\\s*\\(\\d{4}\\)\\s*', '', title).strip()
            context = {
                "title": clean_title,
                "year": year,
                "date": date_str,
                "channel": channel_name,
                "tmdb": tmdb_hint,
            }
            template = s.get("movie_template") or self._DEFAULT_TEMPLATES["movie"]
        else:
            context = {"title": title, "date": date_str, "channel": channel_name, "tmdb": tmdb_hint}
            template = s.get("default_template") or self._DEFAULT_TEMPLATES["default"]

        try:
            filename = template.format_map(context)
        except (KeyError, ValueError, AttributeError):
            filename = f"{title} - {date_str}"

        if program_type == "tv_show" and not context.get("title"):
            filename = self._trim_empty_title_separator(filename)
        return self.sanitize_filename(filename) + ".ts"
'''
    namer.write_text(text[:start] + replacement + text[end:])

    settings = Path("backend/api/settings.py")
    text = settings.read_text()
    # The existing Settings UI renders these variable lists automatically.
    for marker in (
        '{"name": "date", "description": "Air date (YYYY-MM-DD)"},',
        '{"name": "year", "description": "Release year"},',
        '{"name": "channel", "description": "Channel name"},',
    ):
        pass
    text = text.replace(
        '                {"name": "date", "description": "Air date (YYYY-MM-DD)"},\n',
        '                {"name": "date", "description": "Air date (YYYY-MM-DD)"},\n                {"name": "tmdb", "description": "Plex/Jellyfin TMDB hints from an existing guide TMDB ID"},\n',
        1,
    )
    text = text.replace(
        '                {"name": "year", "description": "Release year"},\n',
        '                {"name": "year", "description": "Release year"},\n                {"name": "tmdb", "description": "Plex/Jellyfin TMDB hints from an existing guide TMDB ID"},\n',
        1,
    )
    # Sports and default each have a Channel variable; add to both occurrences.
    channel_line = '                {"name": "channel", "description": "Channel name"},\n'
    replacement_line = channel_line + '                {"name": "tmdb", "description": "Plex/Jellyfin TMDB hints from an existing guide TMDB ID"},\n'
    if text.count(channel_line) < 2:
        raise RuntimeError("expected sports/default channel variables not found")
    text = text.replace(channel_line, replacement_line, 2)
    settings.write_text(text)

    changelog = Path("CHANGELOG.md")
    text = changelog.read_text()
    title = "### Improved: Structured episode and TMDB filename templates"
    if title not in text:
        marker = "---\n\n"
        pos = text.index(marker) + len(marker)
        entry = '''## 2026-08-17

### Improved: Structured episode and TMDB filename templates

**What you would notice:** TV filename templates can now use season/episode metadata supplied directly by the guide even when the title does not contain `SxxEyy`. A guide TMDB ID can be rendered with `{tmdb}`, producing both Plex `{tmdb-ID}` and Jellyfin `[tmdbid-ID]` hints without any TMDB network lookup. Providers that explicitly encode an unknown XMLTV season as `-1` use the airing year for the filename season; genuine `S00` specials remain season 0.

**What changed:** `FileNamer` now consumes optional structured season, episode, subtitle, raw XMLTV season and TMDB fields directly. Custom TV templates remain in effect when the subtitle is blank, with a trailing empty-title separator removed. `{tmdb}` accepts `series/ID`, `movie/ID` or a plain numeric ID, and the Settings template-variable help exposes the token.

---

'''
        changelog.write_text(text[:pos] + entry + text[pos:])

    git("add", "-A")
    git("diff", "--check")


def publish():
    git("add", "-A")
    git("commit", "-m", "Support structured filename metadata")
    git("push", "origin", f"HEAD:refs/heads/{TARGET}")


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in {"prepare", "publish"}:
        raise SystemExit("usage: build_pr408_filename.py prepare|publish")
    (prepare if sys.argv[1] == "prepare" else publish)()
