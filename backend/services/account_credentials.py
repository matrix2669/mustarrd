from sqlalchemy.ext.asyncio import AsyncSession

from models import XtreamAccount
from services.credential_crypto import credential_crypto


def encrypt_account_password(password: str) -> str:
    if password is None:
        raise ValueError("Account password is missing")
    return credential_crypto.encrypt(password)


def resolve_account_password(account: XtreamAccount) -> str:
    if account.password_encrypted:
        try:
            return credential_crypto.decrypt(account.password_encrypted)
        except Exception as exc:
            raise ValueError("Unable to decrypt account credentials") from exc

    if account.password:
        return account.password

    raise ValueError("Account password is missing")


async def resolve_account_password_with_migration(
    session: AsyncSession,
    account: XtreamAccount
) -> str:
    if account.password_encrypted:
        return resolve_account_password(account)

    if not account.password:
        raise ValueError("Account password is missing")

    plaintext = account.password
    account.password_encrypted = encrypt_account_password(plaintext)
    account.password = ""
    session.add(account)
    await session.commit()
    return plaintext
