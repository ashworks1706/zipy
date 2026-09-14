"""The Embedder over LiteLLM, for the [models.embedding] role."""

from __future__ import annotations

from collections.abc import Sequence

from engine.core.config import ModelRole
from engine.core.types import OrgId


class LiteLlmEmbedder:
    """Embeddings through litellm.aembedding, batched."""

    def __init__(self, role: ModelRole) -> None:
        self._role = role

    async def embed(self, org_id: OrgId, texts: Sequence[str]) -> list[list[float]]:
        """One vector per text, each role.dimensions long."""
        raise NotImplementedError
