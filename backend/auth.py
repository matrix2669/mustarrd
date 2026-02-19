import base64
import hashlib
import hmac
import os

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_session
from models import AppSettings


SESSION_ADMIN_KEY = "is_admin"


async def get_or_create_app_settings(session: AsyncSession) -> AppSettings:
    result = await session.execute(select(AppSettings))
    app_settings = result.scalar_one_or_none()
    if app_settings is None:
        app_settings = AppSettings()
        session.add(app_settings)
        await session.commit()
        await session.refresh(app_settings)
    return app_settings


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
    salt_b64 = base64.urlsafe_b64encode(salt).decode("ascii")
    digest_b64 = base64.urlsafe_b64encode(digest).decode("ascii")
    return f"scrypt$16384$8$1${salt_b64}${digest_b64}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, n_value, r_value, p_value, salt_b64, digest_b64 = password_hash.split("$", 5)
    except ValueError:
        return False

    if algorithm != "scrypt":
        return False

    try:
        salt = base64.urlsafe_b64decode(salt_b64.encode("ascii"))
        expected_digest = base64.urlsafe_b64decode(digest_b64.encode("ascii"))
        n_value_int = int(n_value)
        r_value_int = int(r_value)
        p_value_int = int(p_value)
    except Exception:
        return False

    actual_digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=n_value_int,
        r=r_value_int,
        p=p_value_int,
    )
    return hmac.compare_digest(actual_digest, expected_digest)


async def require_admin(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> None:
    app_settings = await get_or_create_app_settings(session)

    # First-run behavior: keep pages open until an admin password is configured.
    if not app_settings.admin_password_hash:
        return

    if request.session.get(SESSION_ADMIN_KEY) is True:
        return

    raise HTTPException(status_code=401, detail="Authentication required")
