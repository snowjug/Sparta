"""Application-level field encryption (Fernet / MultiFernet with key rotation).

Call content and personal data are encrypted *before* they reach the database, so they are protected in backups and
snapshots regardless of the storage engine. The first key encrypts, every key can decrypt, so rotation is: add a new key
at the front of ``SPARTA_DATA_KEYS``, deploy, optionally re-encrypt, then retire the old key.
"""

import base64
import contextlib
import hashlib
import hmac
import secrets
from collections.abc import Callable
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from sparta.config import Settings


class EncryptionUnavailable(RuntimeError):
    pass


class DecryptionError(RuntimeError):
    """The ciphertext cannot be read with any configured key (wrong or retired key). Never includes the ciphertext."""


class FieldCipher:
    def __init__(self, keys: list[str]) -> None:
        if not keys:
            raise EncryptionUnavailable("at least one data key is required")
        try:
            self._fernet = MultiFernet([Fernet(k.encode()) for k in keys])
        except (ValueError, TypeError) as exc:
            raise EncryptionUnavailable(
                "SPARTA_DATA_KEYS must be comma-separated Fernet keys (generate one with `sparta keygen`)"
            ) from exc

    def encrypt(self, plaintext: bytes) -> bytes:
        return self._fernet.encrypt(plaintext)

    def decrypt(self, token: bytes) -> bytes:
        try:
            return self._fernet.decrypt(token)
        except InvalidToken as exc:
            raise DecryptionError("stored value cannot be decrypted with the configured data keys") from exc


def generate_key() -> str:
    return Fernet.generate_key().decode()


def _dev_secret(data_dir: str, name: str, factory: Callable[[], str]) -> str:
    """Stable per-installation development secret kept under the (git-ignored) data directory."""
    path = Path(data_dir) / name
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    value = factory()
    path.write_text(value, encoding="utf-8")
    # chmod is unsupported on some filesystems (e.g. Windows ACLs); the directory is git-ignored anyway
    with contextlib.suppress(OSError):
        path.chmod(0o600)
    return value


def cipher_from_settings(settings: Settings) -> FieldCipher:
    if settings.data_keys is not None:
        return FieldCipher([k.strip() for k in settings.data_keys.get_secret_value().split(",") if k.strip()])
    if settings.is_production:  # unreachable (Settings refuses it) but fail closed anyway
        raise EncryptionUnavailable("SPARTA_DATA_KEYS is required in production")
    if settings.env.value == "test":
        return FieldCipher([generate_key()])
    return FieldCipher([_dev_secret(settings.data_dir, "dev-data.key", generate_key)])


def pepper_from_settings(settings: Settings) -> bytes:
    if settings.pepper is not None:
        return settings.pepper.get_secret_value().encode()
    if settings.is_production:
        raise EncryptionUnavailable("SPARTA_PEPPER is required in production")
    if settings.env.value == "test":
        return b"test-pepper"
    return _dev_secret(settings.data_dir, "dev-pepper.key", lambda: secrets.token_urlsafe(32)).encode()


def user_salt(pepper: bytes, user_id: str) -> bytes:
    """Per-user HMAC key for caller-number fingerprints (shared with the Android app as base64)."""
    return hmac.new(pepper, f"fingerprint-salt:{user_id}".encode(), hashlib.sha256).digest()


def salt_b64(pepper: bytes, user_id: str) -> str:
    return base64.b64encode(user_salt(pepper, user_id)).decode()
