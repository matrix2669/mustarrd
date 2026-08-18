#!/usr/bin/env python3
import subprocess
import sys
from pathlib import Path

UPSTREAM = "df494fe35bc25b93a08b736226e77210b38c83a2"
TARGET = "agent/structured-epg-classification"


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
    Path("backend/tests/test_structured_epg_classification.py").write_text(
        Path("/tmp/pr408-test_structured_epg_classification.py").read_text()
    )

    service = Path("backend/services/epg_service.py")
    text = service.read_text()
    start = text.index("    def detect_program_type(self, program: dict, channel: dict = None) -> str:\n")
    end = text.index("\n\n# Global instance", start)
    method = '''    def detect_program_type(self, program: dict, channel: dict = None) -> str:
        """Classify a programme using structured metadata before heuristics."""
        import re

        title = (program.get("title") or "").strip()
        description = (program.get("description") or "").strip()
        subtitle = (program.get("subtitle") or "").strip()
        full_text = f"{title} {subtitle} {description}".strip()
        title_lower = title.lower()
        channel_category = ((channel or {}).get("category_name") or "").strip().lower()

        raw_categories = program.get("categories") or []
        if isinstance(raw_categories, str):
            raw_categories = [raw_categories]
        categories = [str(value).strip().lower() for value in raw_categories if str(value).strip()]
        primary = (program.get("category") or "").strip().lower()
        if primary and primary not in categories:
            categories.insert(0, primary)

        def has_category(*needles):
            return any(any(needle in value for needle in needles) for value in categories)

        # Strong movie/news metadata wins before any sports fallback.
        tmdb_id = str(program.get("tmdb_id") or "").strip().lower()
        dd_progid = str(program.get("dd_progid") or "").strip().upper()
        if tmdb_id.startswith("movie/") or dd_progid.startswith("MV") or has_category(
            "movie", "film", "cinema", "pelicula"
        ):
            return "movie"

        news_words = ("news", "noticias", "journal", "breaking")
        if has_category("news", "noticias", "information") or any(
            re.search(rf"\\b{re.escape(word)}\\b", title_lower) for word in news_words
        ):
            return "news"

        # Explicit series identity beats a generic Sports category.
        has_structured_episode = (
            program.get("season_number") is not None
            or program.get("episode_number") is not None
            or bool(program.get("episode_onscreen"))
            or bool(program.get("episode_xmltv_ns"))
        )
        if has_category("series") or has_structured_episode:
            return "tv_show"

        if FileNamer.extract_season_episode(full_text) or re.search(
            r"\\b(?:season|episode|ep)\\.?\\s*\\d{1,4}\\b", full_text, re.IGNORECASE
        ):
            return "tv_show"

        # Matchups require real text on both sides. A bare Roman numeral such
        # as "Henry V" must never be interpreted as "versus".
        matchup = re.search(
            r"\\b\\w[\\w.'’&-]*\\s+(?:vs?\\.?|at|@)\\s+\\w[\\w.'’&-]*\\b",
            f"{title} {subtitle}",
            re.IGNORECASE,
        )
        event_words = re.search(
            r"\\b(?:nba|wnba|nfl|mlb|nhl|ncaa|ufc|football|baseball|basketball|soccer|hockey|tennis|golf|boxing|mma|wrestling|rugby|cricket|race|racing|cup|tournament|championship|finals?|playoffs?)\\b",
            f"{title} {subtitle}",
            re.IGNORECASE,
        )
        sports_metadata = has_category("sports", "sport")
        # A strong event/league word is sufficient on its own (preserving the
        # existing NBA/NFL/etc. title heuristics). A generic matchup needs a
        # Sports category so ordinary prose cannot become a game by accident.
        if event_words or (sports_metadata and matchup):
            return "sports"

        # External series identifiers are useful for sparse non-event rows, but
        # come after the event test because providers also attach series IDs to
        # recurring league/game programme families.
        tvdb_id = str(program.get("tvdb_id") or "").strip().lower()
        if tvdb_id.startswith("series/") or tmdb_id.startswith("series/") or dd_progid.startswith(("SH", "EP")):
            return "tv_show"

        # Strong channel categories are late fallbacks so programme metadata wins.
        movie_categories = ("movie", "movies", "film", "films", "cinema", "peliculas")
        if any(value in channel_category for value in movie_categories):
            return "movie"
        if any(value in channel_category for value in ("news", "noticias", "information")):
            return "news"

        filler = re.fullmatch(
            r"\\s*(?:paid programming|to be announced|tba|off air)\\s*",
            title,
            re.IGNORECASE,
        )
        if filler:
            return "other"

        if sports_metadata or "sport" in channel_category:
            return "sports"

        return "other"
'''
    service.write_text(text[:start] + method + text[end:])

    changelog = Path("CHANGELOG.md")
    text = changelog.read_text()
    title = "### Improved: Guide classification uses structured programme metadata"
    if title not in text:
        marker = "---\n\n"
        pos = text.index(marker) + len(marker)
        entry = '''## 2026-08-17

### Improved: Guide classification uses structured programme metadata

**What you would notice:** Series-style sports programmes such as `30 for 30` and `MLB Tonight` can be treated as TV shows when the guide identifies them as a series, while actual matchups remain sports. Sparse programmes on sports channels still fall back to sports unless they are known filler such as Paid Programming, To Be Announced or Off Air. Titles such as `Henry V` are no longer mistaken for a sports matchup.

**What changed:** Programme classification now considers all supplied categories, structured season/episode fields and external series identifiers before falling back to title/channel heuristics. Sports matchup detection requires words on both sides of `vs`, `at` or `@`, while established league/event title keywords remain sports signals; movie/news/series signals take precedence over a generic sports-channel fallback.

---

'''
        changelog.write_text(text[:pos] + entry + text[pos:])

    git("add", "-A")
    git("diff", "--check")


def publish():
    git("add", "-A")
    git("commit", "-m", "Improve structured EPG classification")
    git("push", "origin", f"HEAD:refs/heads/{TARGET}")


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in {"prepare", "publish"}:
        raise SystemExit("usage: build_pr408_classification.py prepare|publish")
    (prepare if sys.argv[1] == "prepare" else publish)()
