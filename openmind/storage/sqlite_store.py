from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator

from openmind.core.models import FileRecord, Source, StatusSummary


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class SQLiteStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sources (
                  id TEXT PRIMARY KEY,
                  path TEXT NOT NULL UNIQUE,
                  recursive INTEGER NOT NULL DEFAULT 1,
                  enabled INTEGER NOT NULL DEFAULT 1,
                  created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS files (
                  id TEXT PRIMARY KEY,
                  source_id TEXT NOT NULL,
                  path TEXT NOT NULL UNIQUE,
                  name TEXT NOT NULL,
                  extension TEXT NOT NULL,
                  size INTEGER NOT NULL,
                  modified_at REAL NOT NULL,
                  content_hash TEXT NOT NULL,
                  status TEXT NOT NULL,
                  indexed_at TEXT,
                  error TEXT,
                  FOREIGN KEY(source_id) REFERENCES sources(id)
                );

                CREATE TABLE IF NOT EXISTS index_runs (
                  id TEXT PRIMARY KEY,
                  started_at TEXT NOT NULL,
                  finished_at TEXT,
                  files_seen INTEGER NOT NULL DEFAULT 0,
                  files_indexed INTEGER NOT NULL DEFAULT 0,
                  files_skipped INTEGER NOT NULL DEFAULT 0,
                  errors INTEGER NOT NULL DEFAULT 0
                );
                """
            )

    def add_source(self, source: Source) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO sources (id, path, recursive, enabled, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    source.id,
                    source.path,
                    int(source.recursive),
                    int(source.enabled),
                    source.created_at,
                ),
            )

    def list_sources(self, enabled_only: bool = False) -> list[Source]:
        query = "SELECT * FROM sources"
        params: tuple[int, ...] = ()
        if enabled_only:
            query += " WHERE enabled = ?"
            params = (1,)
        query += " ORDER BY created_at ASC"
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            Source(
                id=row["id"],
                path=row["path"],
                recursive=bool(row["recursive"]),
                enabled=bool(row["enabled"]),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def remove_source(self, source_id: str) -> bool:
        with self.connect() as conn:
            cur = conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
            return cur.rowcount > 0

    def file_by_path(self, path: str) -> FileRecord | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM files WHERE path = ?", (path,)).fetchone()
        if row is None:
            return None
        return self._file_from_row(row)

    def upsert_file(self, record: FileRecord) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO files (
                  id, source_id, path, name, extension, size, modified_at,
                  content_hash, status, indexed_at, error
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                  source_id = excluded.source_id,
                  name = excluded.name,
                  extension = excluded.extension,
                  size = excluded.size,
                  modified_at = excluded.modified_at,
                  content_hash = excluded.content_hash,
                  status = excluded.status,
                  indexed_at = excluded.indexed_at,
                  error = excluded.error
                """,
                (
                    record.id,
                    record.source_id,
                    record.path,
                    record.name,
                    record.extension,
                    record.size,
                    record.modified_at,
                    record.content_hash,
                    record.status,
                    record.indexed_at,
                    record.error,
                ),
            )

    def status(self, app_home: str) -> StatusSummary:
        with self.connect() as conn:
            sources = conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
            enabled_sources = conn.execute(
                "SELECT COUNT(*) FROM sources WHERE enabled = 1"
            ).fetchone()[0]
            files = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
            indexed_files = conn.execute(
                "SELECT COUNT(*) FROM files WHERE status = 'indexed'"
            ).fetchone()[0]
        return StatusSummary(
            sources=sources,
            enabled_sources=enabled_sources,
            files=files,
            indexed_files=indexed_files,
            app_home=app_home,
        )

    def _file_from_row(self, row: sqlite3.Row) -> FileRecord:
        return FileRecord(
            id=row["id"],
            source_id=row["source_id"],
            path=row["path"],
            name=row["name"],
            extension=row["extension"],
            size=row["size"],
            modified_at=row["modified_at"],
            content_hash=row["content_hash"],
            status=row["status"],
            indexed_at=row["indexed_at"],
            error=row["error"],
        )
