"""Fernet encryption of credentials at rest."""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken
from pydantic import SecretStr

from engine.core.types import ConfigError, StoreError


class Vault:
    """Encrypts and decrypts token strings with the configured Fernet key."""

    def __init__(self, key: SecretStr) -> None:
        raw = key.get_secret_value()
        if not raw:
            raise ConfigError("data.fernet_key is empty; just fernet-key prints one")
        try:
            self._fernet = Fernet(raw)
        except (ValueError, TypeError) as exc:
            raise ConfigError("data.fernet_key is not a urlsafe base64 32-byte key") from exc

    def seal(self, plaintext: SecretStr) -> bytes:
        """The ciphertext of a token."""
        return self._fernet.encrypt(plaintext.get_secret_value().encode())

    def open(self, ciphertext: bytes) -> SecretStr:
        """The token a ciphertext holds. A wrong key is a StoreError."""
        try:
            opened = self._fernet.decrypt(ciphertext)
        except InvalidToken as exc:
            raise StoreError("a sealed value does not open with data.fernet_key") from exc
        return SecretStr(opened.decode())
