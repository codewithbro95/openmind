from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from openmind.core.models import Chunk, SearchResult


class LanceStore:
    def __init__(self, db_path: Path, table_name: str = "chunks"):
        self.db_path = db_path
        self.table_name = table_name
        self._db = None

    @property
    def db(self):
        if self._db is None:
            import lancedb

            self.db_path.mkdir(parents=True, exist_ok=True)
            self._db = lancedb.connect(str(self.db_path))
        return self._db

    def initialize(self) -> None:
        self.db_path.mkdir(parents=True, exist_ok=True)

    def add_chunks(self, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors must have the same length")
        if not chunks:
            return
        indexed_at = datetime.now(UTC).isoformat()
        rows = [
            {
                "id": chunk.id,
                "source_id": chunk.source_id,
                "file_id": chunk.file_id,
                "path": chunk.path,
                "file_name": chunk.file_name,
                "extension": chunk.extension,
                "title": chunk.title,
                "text": chunk.text,
                "vector": vector,
                "chunk_index": chunk.chunk_index,
                "content_hash": chunk.content_hash,
                "modified_at": chunk.modified_at,
                "indexed_at": indexed_at,
                "metadata": json.dumps(chunk.metadata, ensure_ascii=True),
            }
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        table = self._table_or_none()
        if table is None:
            self.db.create_table(self.table_name, data=rows)
        else:
            table.add(rows)

    def delete_file_chunks(self, file_id: str) -> None:
        table = self._table_or_none()
        if table is None:
            return
        table.delete(f"file_id = '{file_id}'")

    def search(self, vector: list[float], limit: int = 5) -> list[SearchResult]:
        table = self._table_or_none()
        if table is None:
            return []
        rows = table.search(vector).limit(limit).to_list()
        return [self._result_from_row(row) for row in rows]

    def _table_or_none(self):
        if self.table_name not in self.db.table_names():
            return None
        return self.db.open_table(self.table_name)

    def _result_from_row(self, row: dict[str, Any]) -> SearchResult:
        distance = float(row.get("_distance", 0.0))
        score = 1.0 / (1.0 + distance)
        text = str(row.get("text", ""))
        snippet = text[:280].replace("\n", " ").strip()
        metadata_raw = row.get("metadata") or "{}"
        try:
            metadata = json.loads(metadata_raw)
        except json.JSONDecodeError:
            metadata = {}
        return SearchResult(
            id=str(row["id"]),
            path=str(row["path"]),
            file_name=str(row["file_name"]),
            title=str(row["title"]),
            text=text,
            snippet=snippet,
            score=score,
            chunk_index=int(row["chunk_index"]),
            metadata=metadata,
        )
