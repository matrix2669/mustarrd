from __future__ import annotations

import json
import logging
from urllib.parse import quote
from typing import Iterable

import aiohttp
from defusedxml import ElementTree as ET


PLEX_PRODUCT = "Mustarrd"
PLEX_CLIENT_ID = "mustarrd-web-client"
logger = logging.getLogger(__name__)


class PlexService:
    @staticmethod
    def _normalize_uri(uri: str | None) -> str:
        return str(uri or "").strip().rstrip("/")

    def allowed_resource_connection_uris(self, resources: list[dict], resource_id: str) -> set[str]:
        wanted_id = str(resource_id or "").strip()
        allowed: set[str] = set()
        for resource in resources or []:
            if str(resource.get("resource_id") or "").strip() != wanted_id:
                continue
            base_url = self._normalize_uri(resource.get("base_url"))
            if base_url:
                allowed.add(base_url)
            for conn in resource.get("connections") or []:
                if not isinstance(conn, dict):
                    continue
                conn_uri = self._normalize_uri(conn.get("uri"))
                if conn_uri:
                    allowed.add(conn_uri)
        return allowed

    def resolve_resource_connection(
        self,
        resources: list[dict],
        resource_id: str,
        requested_uri: str | None = None,
    ) -> dict | None:
        wanted_id = str(resource_id or "").strip()
        target = self._normalize_uri(requested_uri)
        for resource in resources or []:
            if str(resource.get("resource_id") or "").strip() != wanted_id:
                continue
            connections = [
                conn for conn in (resource.get("connections") or [])
                if isinstance(conn, dict) and self._normalize_uri(conn.get("uri"))
            ]
            if target:
                for conn in connections:
                    if self._normalize_uri(conn.get("uri")) == target:
                        return {"uri": self._normalize_uri(conn.get("uri")), "local": bool(conn.get("local"))}
                base_url = self._normalize_uri(resource.get("base_url"))
                if base_url == target:
                    return {"uri": base_url, "local": False}
                return None

            if connections:
                connections.sort(
                    key=lambda conn: (
                        0 if bool(conn.get("local")) else 1,
                        0 if not bool(conn.get("relay")) else 1,
                    )
                )
                best = connections[0]
                return {"uri": self._normalize_uri(best.get("uri")), "local": bool(best.get("local"))}

            base_url = self._normalize_uri(resource.get("base_url"))
            if base_url:
                return {"uri": base_url, "local": False}
            return None
        return None

    def _headers(self, token: str | None = None) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "X-Plex-Product": PLEX_PRODUCT,
            "X-Plex-Client-Identifier": PLEX_CLIENT_ID,
        }
        if token:
            headers["X-Plex-Token"] = token
            headers["Authorization"] = f"Bearer {token}"
        return headers

    async def create_pin(self) -> dict:
        url = "https://plex.tv/api/v2/pins"
        params = {"strong": "true"}
        async with aiohttp.ClientSession() as session:
            async with session.post(url, params=params, headers=self._headers()) as resp:
                if resp.status >= 400:
                    text = await resp.text()
                    raise ValueError(f"Plex PIN create failed: {text}")
                data = await resp.json()

        code = data.get("code")
        pin_id = data.get("id")
        if not code or not pin_id:
            raise ValueError("Plex PIN response missing required fields")

        auth_url = (
            "https://app.plex.tv/auth#?"
            f"clientID={quote(PLEX_CLIENT_ID)}"
            f"&code={quote(str(code))}"
            "&context%5Bdevice%5D%5Bproduct%5D=Mustarrd"
        )

        return {
            "id": pin_id,
            "code": code,
            "auth_url": auth_url,
            "expires_in": data.get("expiresIn"),
        }

    async def check_pin(self, pin_id: int) -> dict:
        url = f"https://plex.tv/api/v2/pins/{pin_id}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self._headers()) as resp:
                if resp.status >= 400:
                    text = await resp.text()
                    raise ValueError(f"Plex PIN check failed: {text}")
                return await resp.json()

    async def get_user_profile(self, token: str) -> dict:
        url = "https://plex.tv/api/v2/user"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self._headers(token)) as resp:
                if resp.status >= 400:
                    text = await resp.text()
                    raise ValueError(f"Plex user lookup failed: {text}")
                return await resp.json()

    async def list_owned_resources(self, token: str) -> list[dict]:
        url = "https://plex.tv/api/v2/resources"
        params = {"includeHttps": "1", "includeRelay": "1"}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers=self._headers(token)) as resp:
                if resp.status >= 400:
                    text = await resp.text()
                    raise ValueError(f"Plex resources lookup failed: {text}")
                content_type = (resp.headers.get("Content-Type") or "").lower()
                body = await resp.text()

        raw_resources: list[dict] = []
        payload = body.lstrip()
        if not payload:
            return []

        if payload.startswith("[") or payload.startswith("{") or "json" in content_type:
            parsed = json.loads(payload)
            if isinstance(parsed, list):
                raw_resources = [item for item in parsed if isinstance(item, dict)]
            elif isinstance(parsed, dict):
                for key in ("resources", "MediaContainer"):
                    value = parsed.get(key)
                    if isinstance(value, list):
                        raw_resources.extend([item for item in value if isinstance(item, dict)])
        else:
            root = ET.fromstring(payload)
            for device in root.findall(".//Device"):
                raw_resources.append(dict(device.attrib))

        resources: list[dict] = []
        for item in raw_resources:
            provides = str(item.get("provides") or "")
            if "server" not in provides.lower():
                continue
            connections = item.get("connections") or item.get("Connection") or []
            if isinstance(connections, dict):
                connections = [connections]
            if not isinstance(connections, list):
                connections = []
            base_url = None
            normalized_connections: list[dict] = []
            for conn in connections:
                if not isinstance(conn, dict):
                    continue
                uri = conn.get("uri")
                if uri:
                    normalized_uri = str(uri).rstrip("/")
                    normalized_connections.append(
                        {
                            "uri": normalized_uri,
                            "local": str(conn.get("local", "")).lower() in {"1", "true"},
                            "relay": str(conn.get("relay", "")).lower() in {"1", "true"},
                            "protocol": conn.get("protocol"),
                            "address": conn.get("address"),
                            "port": conn.get("port"),
                        }
                    )
                    base_url = normalized_uri
                    if str(conn.get("local", "")).lower() in {"1", "true"}:
                        break
            resources.append(
                {
                    "resource_id": str(item.get("clientIdentifier") or item.get("machineIdentifier") or item.get("id") or ""),
                    "name": item.get("name") or item.get("product") or item.get("sourceTitle") or "Plex Server",
                    "product": item.get("product"),
                    "platform": item.get("platform"),
                    "machine_identifier": item.get("clientIdentifier") or item.get("machineIdentifier"),
                    "base_url": base_url,
                    "connections": normalized_connections,
                    "owned": str(item.get("owned", "1")).lower() in {"1", "true", "yes"},
                }
            )
        return [r for r in resources if r.get("resource_id") and r.get("owned")]

    async def list_server_libraries(
        self,
        base_url: str,
        token: str,
        allowed_uris: Iterable[str] | None = None,
    ) -> list[dict]:
        normalized_base_url = self._normalize_uri(base_url)
        if allowed_uris is not None:
            normalized_allowed = {self._normalize_uri(uri) for uri in allowed_uris if self._normalize_uri(uri)}
            if normalized_base_url not in normalized_allowed:
                raise ValueError("Selected Plex connection is not allowed")

        url = f"{normalized_base_url}/library/sections"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self._headers(token)) as resp:
                if resp.status >= 400:
                    text = await resp.text()
                    raise ValueError(f"Plex libraries lookup failed: {text}")
                content_type = (resp.headers.get("Content-Type") or "").lower()
                body = await resp.text()

        payload = body.lstrip()
        if not payload:
            return []

        directories: list[dict] = []
        if payload.startswith("<") or "xml" in content_type:
            root = ET.fromstring(payload)
            for elem in root.findall(".//Directory"):
                directories.append(dict(elem.attrib))
        else:
            parsed = json.loads(payload)
            mc = parsed.get("MediaContainer", {}) if isinstance(parsed, dict) else {}
            dirs = mc.get("Directory", [])
            if isinstance(dirs, list):
                directories = [d for d in dirs if isinstance(d, dict)]

        normalized = []
        for d in directories:
            key = str(d.get("key") or "").strip()
            if not key:
                continue
            normalized.append(
                {
                    "id": key,
                    "title": d.get("title") or f"Library {key}",
                    "type": d.get("type"),
                    "agent": d.get("agent"),
                }
            )
        return normalized

    async def list_server_users(self, base_url: str, server_token: str) -> list[dict]:
        url = f"{base_url.rstrip('/')}/accounts"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self._headers(server_token)) as resp:
                if resp.status >= 400:
                    text = await resp.text()
                    raise ValueError(f"Plex server users lookup failed: {text}")
                content_type = (resp.headers.get("Content-Type") or "").lower()
                body = await resp.text()

        payload = body.lstrip()
        if not payload:
            raise ValueError("Plex server users lookup returned an empty response body")

        root = None
        parse_error = None
        if payload.startswith("<") or "xml" in content_type:
            try:
                root = ET.fromstring(payload)
            except Exception as exc:
                parse_error = exc
        elif payload.startswith("{") or payload.startswith("[") or "json" in content_type:
            try:
                parsed_json = json.loads(payload)
                if isinstance(parsed_json, dict):
                    users = []
                    media_container = parsed_json.get("MediaContainer")
                    if isinstance(media_container, dict):
                        for key in ("accounts", "users", "Account", "User"):
                            value = media_container.get(key)
                            if isinstance(value, list):
                                users.extend([item for item in value if isinstance(item, dict)])
                    for key in ("accounts", "users", "Account", "User"):
                        value = parsed_json.get(key)
                        if isinstance(value, list):
                            users.extend([item for item in value if isinstance(item, dict)])
                    if users:
                        return users
                raise ValueError("Unexpected JSON structure from Plex users endpoint")
            except Exception as exc:
                parse_error = exc

        if root is None:
            preview = payload[:200].replace("\n", "\\n")
            logger.error(
                "Plex users response parse failed url=%s content_type=%s preview=%s",
                url,
                content_type,
                preview,
                exc_info=parse_error,
            )
            raise ValueError(
                f"Plex users response was not parseable (content-type: {content_type or 'unknown'}). "
                f"First bytes: {preview}"
            )

        users: list[dict] = []
        for elem in root.findall(".//Account") + root.findall(".//User"):
            users.append(dict(elem.attrib))
        return users

    async def user_is_in_server(self, base_url: str, server_token: str, profile: dict) -> bool:
        users = await self.list_server_users(base_url, server_token)
        wanted = {
            str(profile.get("id") or "").strip().lower(),
            str(profile.get("uuid") or "").strip().lower(),
            str(profile.get("username") or "").strip().lower(),
            str(profile.get("email") or "").strip().lower(),
        }
        wanted.discard("")
        if not wanted:
            return False

        for user in users:
            candidates = {
                str(user.get("id") or "").strip().lower(),
                str(user.get("uuid") or "").strip().lower(),
                str(user.get("name") or "").strip().lower(),
                str(user.get("username") or "").strip().lower(),
                str(user.get("email") or "").strip().lower(),
                str(user.get("title") or "").strip().lower(),
            }
            if wanted.intersection(candidates):
                return True
        return False

    async def trigger_library_refresh(self, base_url: str, token: str, section_ids: list[str]) -> list[dict]:
        results: list[dict] = []
        async with aiohttp.ClientSession() as session:
            for section_id in section_ids:
                url = f"{base_url.rstrip('/')}/library/sections/{section_id}/refresh"
                try:
                    async with session.get(url, headers=self._headers(token)) as resp:
                        results.append({
                            "section_id": section_id,
                            "ok": resp.status < 400,
                            "status": resp.status,
                        })
                except Exception as exc:
                    results.append({
                        "section_id": section_id,
                        "ok": False,
                        "error": str(exc),
                    })
        return results

    def parse_section_ids(self, raw: str | None) -> list[str]:
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(v).strip() for v in parsed if str(v).strip()]
        except Exception:
            pass
        return [part.strip() for part in str(raw).split(",") if part.strip()]


plex_service = PlexService()
