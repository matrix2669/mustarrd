import base64
from datetime import datetime, timedelta, timezone
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from models import XtreamAccount
from services.xtream_client import XtreamClient


class EPGService:
    def __init__(self):
        self._cache: dict = {}  # Simple in-memory cache
        self._cache_ttl = 3600  # 1 hour

    def _get_cache_key(self, account_id: int, channel_id: str) -> str:
        return f"{account_id}:{channel_id}"

    def _is_cache_valid(self, cache_key: str) -> bool:
        if cache_key not in self._cache:
            return False
        cached_at = self._cache[cache_key].get("cached_at")
        if not cached_at:
            return False
        return (datetime.utcnow() - cached_at).total_seconds() < self._cache_ttl

    async def _get_client(self, session: AsyncSession, account_id: int) -> XtreamClient:
        result = await session.execute(
            select(XtreamAccount).where(XtreamAccount.id == account_id)
        )
        account = result.scalar_one_or_none()
        if not account:
            raise Exception(f"Account {account_id} not found")

        return XtreamClient(account.server_url, account.username, account.password)

    async def get_categories(self, session: AsyncSession, account_id: int) -> list:
        """Get channel categories for an account."""
        client = await self._get_client(session, account_id)
        try:
            return await client.get_live_categories()
        finally:
            await client.close()

    async def get_channels(
        self,
        session: AsyncSession,
        account_id: int,
        category_id: Optional[str] = None
    ) -> list:
        """Get channels for an account, optionally filtered by category."""
        client = await self._get_client(session, account_id)
        try:
            channels = await client.get_live_streams(category_id)
            # Filter to only channels with catchup enabled
            return [ch for ch in channels if ch.get("tv_archive", 0) == 1]
        finally:
            await client.close()

    async def get_epg_for_channel(
        self,
        session: AsyncSession,
        account_id: int,
        channel_id: str,
        use_cache: bool = True
    ) -> list:
        """Get EPG data for a specific channel."""
        cache_key = self._get_cache_key(account_id, channel_id)

        if use_cache and self._is_cache_valid(cache_key):
            return self._cache[cache_key]["data"]

        client = await self._get_client(session, account_id)
        try:
            epg_data = await client.get_epg(channel_id)

            # Process EPG entries
            processed = []
            for entry in epg_data:
                processed.append(self._process_epg_entry(entry))

            # Cache the results
            self._cache[cache_key] = {
                "data": processed,
                "cached_at": datetime.utcnow()
            }

            return processed
        finally:
            await client.close()

    def _process_epg_entry(self, entry: dict) -> dict:
        """Process and normalize an EPG entry."""
        # Decode base64 title and description if present
        title = entry.get("title", "")
        if title:
            try:
                title = base64.b64decode(title).decode("utf-8")
            except Exception:
                pass

        description = entry.get("description", "")
        if description:
            try:
                description = base64.b64decode(description).decode("utf-8")
            except Exception:
                pass

        # Parse timestamps
        start_timestamp = entry.get("start_timestamp", 0)
        stop_timestamp = entry.get("stop_timestamp", 0)

        start_time = datetime.fromtimestamp(int(start_timestamp), tz=timezone.utc) if start_timestamp else None
        end_time = datetime.fromtimestamp(int(stop_timestamp), tz=timezone.utc) if stop_timestamp else None

        duration_minutes = 0
        if start_time and end_time:
            duration_minutes = int((end_time - start_time).total_seconds() / 60)

        return {
            "id": entry.get("id"),
            "epg_id": entry.get("epg_id"),
            "title": title,
            "description": description,
            "start_time": start_time.isoformat() if start_time else None,
            "end_time": end_time.isoformat() if end_time else None,
            "start_timestamp": start_timestamp,
            "stop_timestamp": stop_timestamp,
            "duration_minutes": duration_minutes,
            "has_archive": entry.get("has_archive", 0) == 1,
            "channel_id": entry.get("channel_id"),
        }

    async def get_past_programs(
        self,
        session: AsyncSession,
        account_id: int,
        channel_id: str,
        days_back: int = 7
    ) -> list:
        """Get past programs that are available for catchup."""
        epg_data = await self.get_epg_for_channel(session, account_id, channel_id)

        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=days_back)

        past_programs = []
        for program in epg_data:
            if not program.get("start_time"):
                continue

            start_time = datetime.fromisoformat(program["start_time"])

            # Include programs that have ended and are within the catchup window
            if start_time >= cutoff and start_time < now:
                if program.get("has_archive", False):
                    past_programs.append(program)

        # Sort by start time, most recent first
        past_programs.sort(key=lambda x: x["start_time"], reverse=True)
        return past_programs

    def detect_program_type(self, program: dict, channel: dict = None) -> str:
        """
        Analyze program metadata to determine content type.

        Returns: 'tv_show', 'movie', 'sports', 'news', or 'other'
        """
        title = program.get("title", "").lower()
        description = program.get("description", "").lower()
        category = ""
        if channel:
            category = channel.get("category_name", "").lower()

        # Check for TV show patterns (season/episode)
        import re
        if re.search(r's\d{1,2}e\d{1,2}|season\s*\d+|episode\s*\d+', title + description, re.IGNORECASE):
            return "tv_show"

        # Check for sports
        sports_keywords = ['vs', 'vs.', ' @ ', 'nfl', 'nba', 'nhl', 'mlb', 'ufc', 'boxing',
                          'soccer', 'football', 'basketball', 'hockey', 'baseball', 'tennis',
                          'golf', 'racing', 'motorsport', 'wrestling', 'mma']
        sports_categories = ['sports', 'deportes', 'sport', 'esports']

        if any(kw in title for kw in sports_keywords) or \
           any(cat in category for cat in sports_categories):
            return "sports"

        # Check for movies
        movie_categories = ['movie', 'movies', 'film', 'films', 'cinema', 'peliculas']
        if any(cat in category for cat in movie_categories):
            return "movie"

        # Check for news
        news_keywords = ['news', 'noticias', 'journal', 'breaking']
        news_categories = ['news', 'noticias', 'information']
        if any(kw in title for kw in news_keywords) or \
           any(cat in category for cat in news_categories):
            return "news"

        return "other"


# Global instance
epg_service = EPGService()
