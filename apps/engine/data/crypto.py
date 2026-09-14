"""Fernet encryption of credentials at rest."""

from __future__ import annotations

from pydantic import SecretStr


class Vault:
    """Encrypts and decrypts token strings with the configured Fernet key."""

    def __init__(self, key: SecretStr) -> None:
        raise NotImplementedError

    def seal(self, plaintext: SecretStr) -> bytes:
        """The ciphertext of a token."""
        raise NotImplementedError

    def open(self, ciphertext: bytes) -> SecretStr:
        """The token a ciphertext holds. A wrong key is a StoreError."""
        raise NotImplementedError
