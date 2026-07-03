from __future__ import annotations

from openmind.embeddings.provider import EmbeddingProvider
from openmind.providers.lmstudio.client import LMStudioClient


class LMStudioEmbeddingProvider(EmbeddingProvider):
    def __init__(self, client: LMStudioClient, model: str, dimension: int | None = None):
        self.client = client
        self.model = model
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        if self._dimension is None:
            self._dimension = len(self.embed(["dimension probe"])[0])
        return self._dimension

    def embed(self, texts: list[str]) -> list[list[float]]:
        if texts and not self.client.is_model_loaded(self.model):
            self.client.load_model(self.model)
        return self.client.embed(self.model, texts)
