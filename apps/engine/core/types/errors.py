"""Every error the engine raises. Each is a ZipyError, so a caller catches one base."""

from __future__ import annotations


class ZipyError(Exception):
    """The base of every engine error."""


class ConfigError(ZipyError):
    """zipy.toml, the environment, a plugin or a per-org override is invalid."""


class StoreError(ZipyError):
    """Postgres or Redis failed or returned something unexpected."""


class UnknownWorkspace(ZipyError):
    """A message came from a workspace that is not linked to any org."""


class PermissionDenied(ZipyError):
    """The member's role may not run this action type."""


class BudgetExceeded(ZipyError):
    """The org has spent its monthly model budget."""


class RateLimited(ZipyError):
    """The member sent more messages than the org allows per minute."""


class ModelError(ZipyError):
    """The model provider failed. retryable is true for timeouts and rate limits."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class CredentialError(ZipyError):
    """The org has no valid credential for a provider."""


class ToolError(ZipyError):
    """A tool call failed. The message goes back to the model as the tool result."""


class ConfirmationError(ZipyError):
    """A confirmation is unknown, expired, or answered by someone who may not answer it."""


class OAuthError(ZipyError):
    """An OAuth exchange or refresh failed, or its state parameter did not verify."""


class PlatformError(ZipyError):
    """A chat platform rejected a send, a read or a connection."""


class IngestError(ZipyError):
    """A document could not be fetched, chunked or embedded."""
