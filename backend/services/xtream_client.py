import aiohttp
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin


class XtreamClient:
    def __init__(self, server_url: str, username: str, password: str):
        self.server_url = server_url.rstrip("/")
        self.username = username
        self.password = password
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30)
            )
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    def _build_api_url(self, action: str, **params) -> str:
        base = f"{self.server_url}/player_api.php"
        params_str = f"username={self.username}&password={self.password}&action={action}"
        for key, value in params.items():
            if value is not None:
                params_str += f"&{key}={value}"
        return f"{base}?{params_str}"

    async def authenticate(self) -> dict:
        """Get server info and validate credentials."""
        url = self._build_api_url("")
        session = await self._get_session()
        async with session.get(url) as response:
            if response.status != 200:
                raise Exception(f"Authentication failed: HTTP {response.status}")
            data = await response.json()
            if "user_info" not in data:
                raise Exception("Invalid response from server")
            return data

    async def get_live_categories(self) -> list:
        """Get list of live TV categories."""
        url = self._build_api_url("get_live_categories")
        session = await self._get_session()
        async with session.get(url) as response:
            if response.status != 200:
                raise Exception(f"Failed to get categories: HTTP {response.status}")
            return await response.json()

    async def get_live_streams(self, category_id: Optional[str] = None) -> list:
        """Get list of live streams/channels."""
        url = self._build_api_url("get_live_streams", category_id=category_id)
        session = await self._get_session()
        async with session.get(url) as response:
            if response.status != 200:
                raise Exception(f"Failed to get streams: HTTP {response.status}")
            return await response.json()

    async def get_epg(self, stream_id: str) -> list:
        """Get full EPG for a specific channel."""
        url = self._build_api_url("get_simple_data_table", stream_id=stream_id)
        session = await self._get_session()
        async with session.get(url) as response:
            if response.status != 200:
                raise Exception(f"Failed to get EPG: HTTP {response.status}")
            data = await response.json()
            return data.get("epg_listings", [])

    async def get_short_epg(self, stream_id: str, limit: int = 10) -> list:
        """Get short EPG (current + upcoming) for a channel."""
        url = self._build_api_url("get_short_epg", stream_id=stream_id, limit=limit)
        session = await self._get_session()
        async with session.get(url) as response:
            if response.status != 200:
                raise Exception(f"Failed to get short EPG: HTTP {response.status}")
            data = await response.json()
            return data.get("epg_listings", [])

    def build_timeshift_url(
        self,
        stream_id: str,
        start_time: datetime,
        duration_minutes: int
    ) -> str:
        """
        Build catchup/timeshift URL.

        Format: {server}/timeshift/{username}/{password}/{duration}/{YYYY-MM-DD:HH-MM}/{stream_id}.ts
        """
        date_str = start_time.strftime("%Y-%m-%d:%H-%M")
        return f"{self.server_url}/timeshift/{self.username}/{self.password}/{duration_minutes}/{date_str}/{stream_id}.ts"

    def build_stream_url(self, stream_id: str, extension: str = "ts") -> str:
        """Build live stream URL."""
        return f"{self.server_url}/live/{self.username}/{self.password}/{stream_id}.{extension}"
