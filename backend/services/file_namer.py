import re
import unicodedata
from datetime import datetime
from typing import Optional, Tuple


class FileNamer:
    # Device names Windows refuses to use as a filename stem. A program titled
    # "Aux" or "Con" would otherwise produce a file that cannot be created on
    # Windows or written to an SMB share.
    RESERVED_STEMS = re.compile(r'^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?=\.|$)', re.IGNORECASE)

    # Shared season/episode patterns. Order matters: the S/E form is tried first
    # so "S54 E173" doesn't fall through to the looser NxNN form.
    # Covers: S01E01, S54 E173, S54.E173, S54-E173, S04, E12,
    # Season 4 Episode 12, Season 4, Episode 12, S54 Ep. 173, Sn 4 Ep 12
    SEASON_EPISODE_PATTERNS = [
        re.compile(
            r'\b[Ss](?:eason|n)?\s*(\d{1,2})\s*[.,\-]?\s*'
            r'[Ee](?:p(?:isode)?)?\.?\s*(\d{1,4})\b'
        ),
        # 4x12, 54x173 — no spaces around the x, so "3 x 4" in prose doesn't match
        re.compile(r'\b(\d{1,2})[xX](\d{1,4})\b'),
    ]

    # Word-boundary sports detection: bare substrings like 'vs' or 'mma'
    # false-positive inside words ("canvas", "grammar").
    SPORTS_TITLE_PATTERN = re.compile(
        r'\bvs\.?\b'
        r'|@'
        r'|\b(?:nfl|nba|wnba|nhl|mlb|mls|ufc|mma|ncaa|fifa|uefa|f1|nascar|motogp|pga|lpga|atp|wta)\b'
        r'|\b(?:boxing|soccer|football|basketball|hockey|baseball|tennis|golf|racing|motorsport|wrestling|cricket|rugby)\b'
        r'|\b(?:premier league|la liga|serie a|bundesliga|ligue 1|champions league|europa league'
        r'|world cup|stanley cup|super bowl|world series|grand prix)\b'
        r'|\b(?:round|week|matchday)\s+\d+\b'
        r'|\bplayoffs?\b|\bsemi-?finals?\b|\bquarter-?finals?\b',
        re.IGNORECASE,
    )

    SPORTS_CATEGORIES = ['sports', 'deportes', 'sport', 'esports']

    @classmethod
    def sanitize_filename(cls, name: str) -> str:
        """Remove invalid characters for a single filesystem path component."""
        # Remove stylized "New" markers used in some EPG titles
        name = re.sub(r'[\[\(\-–—|:]*\s*ᴺᵉʷ\s*[\]\)]*\s*(?:-\s*)?', ' ', name)
        # Remove stylized "Live" markers frequently injected by providers
        name = re.sub(r'[\[\(\-–—|:]*\s*ᴸᶦᵛᵉ\s*[\]\)]*\s*(?:-\s*)?', ' ', name)

        # Remove invisible Unicode format/directional chars: zero-width, BOM, soft hyphen,
        # and bidi override/isolate controls (U+202A-202E, U+2066-2069) that can make
        # filenames display reversed in terminals and file managers.
        name = re.sub('[\u00ad\u200b\u200c\u200d\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069\ufeff]', '', name)

        # Compose accents so "Amelie" + combining accent and a precomposed
        # "Amélie" land on the same bytes across Linux and macOS.
        name = unicodedata.normalize('NFC', name)

        # Map separators to a dash rather than a space: they almost always join
        # two real words ("AC/DC" reads better as "AC-DC" than "AC DC"), and a
        # colon usually introduces a subtitle ("Star Wars: A New Hope"). A pipe
        # is a common EPG field separator, so it joins two words too.
        name = re.sub(r'[/\\|]', '-', name)
        # An adjacent dash is absorbed so "Show - : The Movie" doesn't end up
        # with two separators in a row.
        name = re.sub(r'\s*-?\s*:\s*', ' - ', name)
        # These are illegal on Windows and sit inside a word rather than
        # between two, so drop them with no gap left ("Who?" -> "Who").
        sanitized = re.sub(r'["<>?*]', '', name)
        # Null bytes and control chars are corruption sitting between two real
        # words, so they become a space rather than fusing the words together.
        sanitized = re.sub(r'[\x00-\x1f]', ' ', sanitized)
        # Remove multiple spaces
        sanitized = re.sub(r'\s+', ' ', sanitized)
        # Collapse dash runs the separator mapping above created ("Show//Name")
        sanitized = re.sub(r'-{2,}', '-', sanitized)
        # Drop a dangling separator dash left by a trailing/leading colon or
        # slash. Only dashes detached by whitespace count, so a title that is
        # genuinely dashed ("-30-") keeps its own.
        sanitized = re.sub(r'^\s*-+\s+|\s+-+\s*$', '', sanitized)
        # Remove leading/trailing spaces and dots. Dashes are otherwise left
        # alone: only dots and spaces are a problem for Windows.
        sanitized = sanitized.strip(' .') or "unknown-program"
        # Limit to 200 UTF-8 bytes so CJK/Arabic titles don't exceed Linux
        # NAME_MAX (255 bytes) when combined with an extension.
        encoded = sanitized.encode("utf-8")
        if len(encoded) > 200:
            sanitized = encoded[:200].decode("utf-8", errors="ignore").rstrip() or "unknown-program"
        # Suffix reserved Windows device stems, including when an extension
        # follows (for example AUX.txt -> AUX_.txt).
        reserved_match = cls.RESERVED_STEMS.match(sanitized)
        if reserved_match:
            stem_end = reserved_match.end()
            sanitized = f"{sanitized[:stem_end]}_{sanitized[stem_end:]}"
        return sanitized

    @classmethod
    def _join_path_components(cls, components) -> str:
        """Sanitize and join path levels, dropping anything that could escape.

        Empty levels are skipped so a leading slash cannot make the result
        absolute, and ``.``/``..`` are dropped entirely so a template or custom
        filename can never traverse above the configured recording folder (nor
        leave a trail of placeholder directories behind when it tries).
        """
        safe = []
        for component in components:
            component = component.strip()
            if not component or component in ('.', '..'):
                continue
            safe.append(cls.sanitize_filename(component))
        return '/'.join(safe) or "unknown-program"

    @classmethod
    def sanitize_relative_path(cls, path: str) -> str:
        """Sanitize an already-rendered relative path while preserving ``/`` levels.

        Each slash-delimited component is sanitized independently. Backslashes
        are folded into the component itself rather than becoming separators.
        """
        return cls._join_path_components(path.split('/'))

    @classmethod
    def sanitize_custom_filename(cls, name: str) -> str:
        """Sanitize a user-supplied recording path, always ending in ``.ts``.

        The extension is stripped before sanitizing so the dot doesn't get
        treated as part of the final path component, then re-added.
        """
        return cls.sanitize_relative_path(name.removesuffix(".ts")) + ".ts"

    @classmethod
    def render_template_path(cls, template: str, context: dict) -> str:
        """Render a filename template as a safe relative path.

        Forward slashes written literally in a saved template create directory
        levels. Each level is formatted and sanitized independently so slashes
        coming from provider metadata (for example a show named ``AC/DC``) stay
        inside that component rather than becoming extra directories.
        """
        return cls._join_path_components(
            component_template.format_map(context)
            for component_template in template.split('/')
        )

    @classmethod
    def extract_season_episode(cls, text: str) -> Optional[Tuple[int, int]]:
        """Extract season and episode numbers from text."""
        for pattern in cls.SEASON_EPISODE_PATTERNS:
            match = pattern.search(text)
            if match:
                return (int(match.group(1)), int(match.group(2)))

        return None

    @classmethod
    def extract_show_name(cls, title: str) -> str:
        """Extract the show name from a title with season/episode info."""
        for pattern in cls.SEASON_EPISODE_PATTERNS:
            match = pattern.search(title)
            if match:
                before = title[:match.start()].strip(' -:,.(')
                if before:
                    return before
                # Pattern at the very start of the title — keep whatever follows
                return pattern.sub('', title, count=1).strip(' -:,.)')

        # Season-only titles like "Show Name Season 4"
        show_name = re.sub(r'\s*[Ss]eason\s*\d+.*$', '', title)
        return show_name.strip(' -:')

    @classmethod
    def extract_episode_title(cls, title: str) -> str:
        """Extract the episode title from a full title."""
        for pattern in cls.SEASON_EPISODE_PATTERNS:
            match = pattern.search(title)
            if match:
                after = title[match.end():]
                sep = re.match(r'\s*[-–:]\s*(.+)$', after)
                if sep:
                    return sep.group(1).strip()
                return ""

        return ""

    @staticmethod
    def extract_year(text: str) -> Optional[int]:
        """Extract a year (1900-2099) from text."""
        match = re.search(r'\b(19\d{2}|20\d{2})\b', text)
        if match:
            return int(match.group(1))
        return None

    @classmethod
    def detect_sports(cls, title: str, category: str = "") -> bool:
        """Check if content is sports-related."""
        category_lower = category.lower()

        return (
            bool(cls.SPORTS_TITLE_PATTERN.search(title)) or
            any(cat in category_lower for cat in cls.SPORTS_CATEGORIES)
        )

    _DEFAULT_TEMPLATES = {
        "tv": "{show} - S{season:02d}E{episode:02d} - {title}",
        "tv_no_subtitle": "{show} - S{season:02d}E{episode:02d}",
        "movie": "{title} ({year})",
        "sports": "{title} - {date}",
        "default": "{title} - {date}",
    }

    @staticmethod
    def _tmdb_hint(value) -> str:
        """Render an existing guide TMDB ID for Plex and Jellyfin templates."""
        raw = str(value or "").strip()
        match = re.fullmatch(r"(?:(?:series|movie)/)?(\d+)", raw, re.IGNORECASE)
        if not match:
            return ""
        tmdb_id = match.group(1)
        return f"{{tmdb-{tmdb_id}}} [tmdbid-{tmdb_id}]"

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
            structured_season = self._structured_season(program, start_time)
            structured_episode = self._coerce_optional_int(program.get("episode_number"))
            full_text = f"{title} {description}"
            parsed_season_ep = self.extract_season_episode(full_text)

            if structured_season is not None and structured_episode is not None:
                show_name = (
                    self.extract_show_name(title)
                    if self.extract_season_episode(title)
                    else title
                )
                episode_title = (
                    program.get("subtitle")
                    or self.extract_episode_title(title)
                    or ""
                ).strip()
                context = {
                    "show": show_name,
                    "season": structured_season,
                    "episode": structured_episode,
                    "title": episode_title,
                    "date": date_str,
                    "channel": channel_name,
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
                episode_title = (
                    program.get("subtitle")
                    or self.extract_episode_title(title)
                    or ""
                ).strip()
                context = {
                    "show": show_name, "season": season_ep[0], "episode": season_ep[1],
                    "title": episode_title, "date": date_str, "channel": channel_name,
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
                context = {
                    "title": title,
                    "date": date_str,
                    "channel": channel_name,
                    "tmdb": tmdb_hint,
                }
                template = s.get("default_template") or self._DEFAULT_TEMPLATES["default"]
        elif program_type == "sports":
            context = {
                "title": title,
                "date": date_str,
                "channel": channel_name,
                "tmdb": tmdb_hint,
            }
            template = s.get("sports_template") or self._DEFAULT_TEMPLATES["sports"]
        elif program_type == "movie":
            year = self.extract_year(description) or self.extract_year(title) or start_time.year
            clean_title = re.sub(r'\s*\(\d{4}\)\s*', '', title).strip()
            context = {
                "title": clean_title,
                "year": year,
                "date": date_str,
                "channel": channel_name,
                "tmdb": tmdb_hint,
            }
            template = s.get("movie_template") or self._DEFAULT_TEMPLATES["movie"]
        else:
            context = {
                "title": title,
                "date": date_str,
                "channel": channel_name,
                "tmdb": tmdb_hint,
            }
            template = s.get("default_template") or self._DEFAULT_TEMPLATES["default"]

        try:
            filename = self.render_template_path(template, context)
        except (KeyError, ValueError, AttributeError):
            filename = self.sanitize_filename(f"{title} - {date_str}")

        return filename + ".ts"


# Global instance
file_namer = FileNamer()
