from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator

from openmind.core.models import FileRecord, IndexJob, Source, StatusSummary


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

                CREATE TABLE IF NOT EXISTS index_jobs (
                  id TEXT PRIMARY KEY,
                  status TEXT NOT NULL,
                  total_files INTEGER DEFAULT 0,
                  processed_files INTEGER DEFAULT 0,
                  indexed_files INTEGER DEFAULT 0,
                  skipped_files INTEGER DEFAULT 0,
                  already_indexed_files INTEGER DEFAULT 0,
                  failed_files INTEGER DEFAULT 0,
                  total_chunks INTEGER DEFAULT 0,
                  current_file TEXT,
                  error TEXT,
                  started_at TEXT,
                  completed_at TEXT,
                  updated_at TEXT
                );
                """
            )
            self._ensure_column(conn, "index_jobs", "already_indexed_files", "INTEGER DEFAULT 0")

    def _ensure_column(
        self,
        conn: sqlite3.Connection,
        table: str,
        column: str,
        definition: str,
    ) -> None:
        columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

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
        return [self._source_from_row(row) for row in rows]

    def source_by_id(self, source_id: str) -> Source | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
        return self._source_from_row(row) if row is not None else None

    def set_source_enabled(self, source_id: str, enabled: bool) -> bool:
        with self.connect() as conn:
            result = conn.execute(
                "UPDATE sources SET enabled = ? WHERE id = ?",
                (int(enabled), source_id),
            )
            return result.rowcount > 0

    def source_is_enabled(self, source_id: str) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT enabled FROM sources WHERE id = ?",
                (source_id,),
            ).fetchone()
        return row is not None and bool(row["enabled"])

    def indexed_file_count_for_source(self, source_id: str) -> int:
        with self.connect() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM files WHERE source_id = ? AND status = 'indexed'",
                (source_id,),
            ).fetchone()[0]

    def remove_source(self, source_id: str) -> int | None:
        with self.connect() as conn:
            source = conn.execute("SELECT 1 FROM sources WHERE id = ?", (source_id,)).fetchone()
            if source is None:
                return None
            files_removed = conn.execute(
                "DELETE FROM files WHERE source_id = ?",
                (source_id,),
            ).rowcount
            conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
            return files_removed

    def orphaned_source_ids(self) -> list[str]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT files.source_id
                FROM files
                LEFT JOIN sources ON sources.id = files.source_id
                WHERE sources.id IS NULL
                """
            ).fetchall()
        return [str(row["source_id"]) for row in rows]

    def delete_files_for_source(self, source_id: str) -> int:
        with self.connect() as conn:
            return conn.execute(
                "DELETE FROM files WHERE source_id = ?",
                (source_id,),
            ).rowcount

    def file_by_path(self, path: str) -> FileRecord | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM files WHERE path = ?", (path,)).fetchone()
        if row is None:
            return None
        return self._file_from_row(row)

    def file_by_id(self, file_id: str) -> FileRecord | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
        if row is None:
            return None
        return self._file_from_row(row)

    def upsert_file(self, record: FileRecord) -> None:
        with self.connect() as conn:
            self._upsert_file(conn, record)

    def upsert_file_if_source_enabled(self, record: FileRecord) -> bool:
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            source = conn.execute(
                "SELECT enabled FROM sources WHERE id = ?",
                (record.source_id,),
            ).fetchone()
            if source is None or not bool(source["enabled"]):
                return False
            self._upsert_file(conn, record)
            return True

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

    def index_state_counts(self) -> dict[str, int]:
        with self.connect() as conn:
            return {
                "sources": conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0],
                "files": conn.execute("SELECT COUNT(*) FROM files").fetchone()[0],
                "indexed_files": conn.execute(
                    "SELECT COUNT(*) FROM files WHERE status = 'indexed'"
                ).fetchone()[0],
                "index_jobs": conn.execute("SELECT COUNT(*) FROM index_jobs").fetchone()[0],
                "index_runs": conn.execute("SELECT COUNT(*) FROM index_runs").fetchone()[0],
            }

    def flush_index_state(self, include_sources: bool = False) -> dict[str, int]:
        counts = self.index_state_counts()
        with self.connect() as conn:
            conn.execute("DELETE FROM files")
            conn.execute("DELETE FROM index_jobs")
            conn.execute("DELETE FROM index_runs")
            if include_sources:
                conn.execute("DELETE FROM sources")
        return counts

    def create_index_job(self, job_id: str) -> IndexJob:
        now = utc_now()
        job = IndexJob(id=job_id, status="pending", started_at=now, updated_at=now)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO index_jobs (
                  id, status, total_files, processed_files, indexed_files,
                  skipped_files, already_indexed_files, failed_files, total_chunks,
                  current_file, error, started_at, completed_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._job_values(job),
            )
        return job

    def update_index_job(self, job_id: str, **updates: object) -> IndexJob:
        if not updates:
            job = self.get_index_job(job_id)
            if job is None:
                raise KeyError(f"Unknown index job: {job_id}")
            return job
        updates["updated_at"] = utc_now()
        assignments = ", ".join(f"{key} = ?" for key in updates)
        values = list(updates.values())
        values.append(job_id)
        with self.connect() as conn:
            conn.execute(f"UPDATE index_jobs SET {assignments} WHERE id = ?", values)
        job = self.get_index_job(job_id)
        if job is None:
            raise KeyError(f"Unknown index job: {job_id}")
        return job

    def get_index_job(self, job_id: str) -> IndexJob | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM index_jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            return None
        return self._job_from_row(row)

    def latest_index_job(self) -> IndexJob | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM index_jobs ORDER BY updated_at DESC, started_at DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        return self._job_from_row(row)

    def latest_active_index_job(self) -> IndexJob | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM index_jobs
                WHERE status IN ('pending', 'discovering', 'running', 'pause_requested', 'paused')
                ORDER BY updated_at DESC, started_at DESC
                LIMIT 1
                """
            ).fetchone()
        if row is None:
            return None
        return self._job_from_row(row)

    def latest_unfinished_index_job(self) -> IndexJob | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM index_jobs
                WHERE status NOT IN ('completed', 'failed', 'stopped')
                ORDER BY updated_at DESC, started_at DESC
                LIMIT 1
                """
            ).fetchone()
        if row is None:
            return None
        return self._job_from_row(row)

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

    def _upsert_file(self, conn: sqlite3.Connection, record: FileRecord) -> None:
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

    def _source_from_row(self, row: sqlite3.Row) -> Source:
        return Source(
            id=row["id"],
            path=row["path"],
            recursive=bool(row["recursive"]),
            enabled=bool(row["enabled"]),
            created_at=row["created_at"],
        )

    def _job_values(self, job: IndexJob) -> tuple[object, ...]:
        return (
            job.id,
            job.status,
            job.total_files,
            job.processed_files,
            job.indexed_files,
            job.skipped_files,
            job.already_indexed_files,
            job.failed_files,
            job.total_chunks,
            job.current_file,
            job.error,
            job.started_at,
            job.completed_at,
            job.updated_at,
        )

    def _job_from_row(self, row: sqlite3.Row) -> IndexJob:
        return IndexJob(
            id=row["id"],
            status=row["status"],
            total_files=row["total_files"],
            processed_files=row["processed_files"],
            indexed_files=row["indexed_files"],
            skipped_files=row["skipped_files"],
            already_indexed_files=row["already_indexed_files"],
            failed_files=row["failed_files"],
            total_chunks=row["total_chunks"],
            current_file=row["current_file"],
            error=row["error"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            updated_at=row["updated_at"],
        )
