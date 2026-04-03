import secrets
from urllib.parse import urlparse

from starlette.requests import HTTPConnection
from starlette.types import Scope


CSRF_SESSION_KEY = "csrf_token"
CSRF_HEADER_NAME = "x-csrf-token"


def ensure_csrf_token(connection: HTTPConnection) -> str:
    token = connection.session.get(CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        connection.session[CSRF_SESSION_KEY] = token
    return str(token)


def normalize_origin(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlparse(value.strip())
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def request_origin(scope: Scope) -> str | None:
    scheme = str(scope.get("scheme") or "http").lower()
    for header_name, header_value in scope.get("headers", []):
        if header_name == b"x-forwarded-proto":
            forwarded = header_value.decode("latin-1").split(",")[0].strip().lower()
            if forwarded:
                scheme = forwarded
            break

    host = None
    for header_name, header_value in scope.get("headers", []):
        if header_name == b"host":
            host = header_value.decode("latin-1").strip().lower()
            break

    if not host:
        return None
    return f"{scheme}://{host}"


def origin_is_allowed(origin: str | None, scope: Scope, allowed_origins: list[str]) -> bool:
    normalized_origin = normalize_origin(origin)
    if not normalized_origin:
        return False

    allowed = {normalize_origin(value) for value in allowed_origins}
    allowed.discard(None)

    current_origin = request_origin(scope)
    if current_origin:
        allowed.add(current_origin)

    return normalized_origin in allowed
