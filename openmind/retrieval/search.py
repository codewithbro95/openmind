from __future__ import annotations

from openmind.core.models import SearchResult
from openmind.embeddings.provider import EmbeddingProvider
from openmind.storage.lance_store import LanceStore


class SearchService:
    def __init__(self, embeddings: EmbeddingProvider, store: LanceStore):
        self.embeddings = embeddings
        self.store = store

    def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        query = query.strip()
        if not query:
            return []
        vector = self.embeddings.embed([query])[0]
        return self.store.search(vector, limit=limit)
