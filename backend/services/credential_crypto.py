import base64
import hashlib
import os
import secrets
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from config import ensure_config_files


class CredentialCrypto:
    def __init__(self):
        self._key: bytes | None = None

    def _key_file(self) -> Path:
        return ensure_config_files() / "credential_key"

    def _decode_env_key(self, value: str) -> bytes:
        raw = value.strip()
        if not raw:
            raise ValueError("Credential key is empty")

        # Accept urlsafe base64 encoded 32-byte keys.
        try:
            padding = "=" * (-len(raw) % 4)
            decoded = base64.urlsafe_b64decode((raw + padding).encode("ascii"))
            if len(decoded) == 32:
                return decoded
        except Exception:
            pass

        # Accept 64-char hex encoded keys.
        try:
            decoded = bytes.fromhex(raw)
            if len(decoded) == 32:
                return decoded
        except Exception:
            pass

        # Fallback: derive a 32-byte key from the provided string.
        return hashlib.sha256(raw.encode("utf-8")).digest()

    def _load_or_create_key(self) -> bytes:
        env_key = os.environ.get("CATCHUP_CREDENTIAL_KEY")
        if env_key:
            return self._decode_env_key(env_key)

        key_file = self._key_file()
        if key_file.exists():
            stored = key_file.read_text(encoding="utf-8").strip()
            if stored:
                return self._decode_env_key(stored)

        key = secrets.token_bytes(32)
        key_file.parent.mkdir(parents=True, exist_ok=True)
        key_file.write_text(base64.urlsafe_b64encode(key).decode("ascii"), encoding="utf-8")
        try:
            os.chmod(key_file, 0o600)
        except Exception:
            pass
        return key

    def _get_key(self) -> bytes:
        if self._key is None:
            self._key = self._load_or_create_key()
        return self._key

    def encrypt(self, plaintext: str) -> str:
        if plaintext is None:
            raise ValueError("Missing plaintext")
        key = self._get_key()
        nonce = secrets.token_bytes(12)
        cipher = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), None)
        payload = base64.urlsafe_b64encode(nonce + cipher).decode("ascii")
        return f"v1:{payload}"

    def decrypt(self, token: str) -> str:
        if not token:
            raise ValueError("Missing encrypted value")
        if not token.startswith("v1:"):
            raise ValueError("Unsupported credential format")

        encoded = token[3:]
        padding = "=" * (-len(encoded) % 4)
        raw = base64.urlsafe_b64decode((encoded + padding).encode("ascii"))
        if len(raw) <= 12:
            raise ValueError("Encrypted payload is invalid")

        nonce = raw[:12]
        ciphertext = raw[12:]
        key = self._get_key()
        decrypted = AESGCM(key).decrypt(nonce, ciphertext, None)
        return decrypted.decode("utf-8")


credential_crypto = CredentialCrypto()
