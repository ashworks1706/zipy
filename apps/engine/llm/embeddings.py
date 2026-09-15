"""The Embedder over LiteLLM, for the [models.embedding] role."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import litellm

from engine.core.config import ModelRole
from engine.core.types import ModelError, OrgId
from engine.llm.client import provider_error


def vectors_of(response: Any, expected: int, model: str) -> list[list[float]]:
    """The embeddings of a response, in input order. A short or empty answer is a ModelError."""
    rows = list(getattr(response, "data", None) or [])
    if len(rows) != expected:
        raise ModelError(
            f"{model} returned {len(rows)} embeddings for {expected} texts", retryable=False
        )
    ordered = sorted(rows, key=lambda row: int(_field(row, "index", 0) or 0))
    return [[float(value) for value in _field(row, "embedding", ())] for row in ordered]


def _field(row: Any, key: str, default: Any) -> Any:
    """One field of an embedding row, which litellm gives as a dict or an object."""
    if isinstance(row, dict):
        return row.get(key, default)
    return getattr(row, key, default)


class LiteLlmEmbedder:
    """Embeddings through litellm.aembedding, batched."""

    def __init__(self, role: ModelRole) -> None:
        self._role = role

    async def embed(
        self,
        org_id: OrgId,  # noqa: ARG002 - protocol signature
        texts: Sequence[str],
    ) -> list[list[float]]:
        """One vector per text, each role.dimensions long."""
        batch = list(texts)
        if not batch:
            return []
        try:
            response = await litellm.aembedding(**self._request(batch))
        except ModelError:
            raise
        except Exception as exc:
            raise provider_error(
                self._role.model, exc, self._role.api_key.get_secret_value()
            ) from exc
        return vectors_of(response, len(batch), self._role.model)

    def _request(self, batch: list[str]) -> dict[str, Any]:
        """The keyword arguments of one litellm embedding call."""
        request: dict[str, Any] = {
            "model": self._role.model,
            "input": batch,
            "timeout": self._role.timeout_secs,
        }
        key = self._role.api_key.get_secret_value()
        if key:
            request["api_key"] = key
        if self._role.api_base:
            request["api_base"] = self._role.api_base
        if self._role.dimensions:
            request["dimensions"] = self._role.dimensions
        return request
