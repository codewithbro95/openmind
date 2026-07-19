from __future__ import annotations

import uuid
from pathlib import Path

from openmind.core.models import Source
from openmind.storage.sqlite_store import SQLiteStore, utc_now


class SourceManager:
    def __init__(self, store: SQLiteStore):
        self.store = store

    def add(self, path: str, recursive: bool = True) -> Source:
        source_path = Path(path).expanduser().resolve()
        if not source_path.exists():
            raise FileNotFoundError(f"Source path does not exist: {source_path}")
        if not source_path.is_dir():
            raise NotADirectoryError(f"Source path is not a directory: {source_path}")
        source = Source(
            id=f"src_{uuid.uuid4().hex[:12]}",
            path=str(source_path),
            recursive=recursive,
            enabled=True,
            created_at=utc_now(),
        )
        self.store.add_source(source)
        return source

    def list(self, enabled_only: bool = False) -> list[Source]:
        return self.store.list_sources(enabled_only=enabled_only)

    def get(self, source_id: str) -> Source | None:
        return self.store.source_by_id(source_id)

    def set_enabled(self, source_id: str, enabled: bool) -> bool:
        return self.store.set_source_enabled(source_id, enabled)

    def remove(self, source_id: str) -> int | None:
        return self.store.remove_source(source_id)
