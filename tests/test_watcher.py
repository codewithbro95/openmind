from __future__ import annotations

import sqlite3
import subprocess

from watchdog.events import FileCreatedEvent, FileDeletedEvent, FileModifiedEvent, FileMovedEvent

from openmind.core.config import AppPaths
from openmind.core.engine import OpenMindEngine
from openmind.core.models import FileRecord, Source
from openmind.embeddings.provider import HashEmbeddingProvider
from openmind.llm.answer import ContextOnlyAnswerProvider
from openmind.sources.scanner import FileScanner
from openmind.storage.sqlite_store import SQLiteStore
from openmind.watcher.debounce import EventDebouncer
from openmind.watcher.events import FileChangeEvent
from openmind.watcher.handler import WatchEventHandler
from openmind.watcher.service import WatchService


class RecordingLanceStore:
    def __init__(self):
        self.deleted_file_ids: list[str] = []
        self.added_chunks = []

    def initialize(self):
        pass

    def add_chunks(self, chunks, vectors):
        self.added_chunks.extend(chunks)

    def delete_file_chunks(self, file_id):
        self.deleted_file_ids.append(file_id)
        return 1

    def delete_source_chunks(self, source_id):
        return 0


def test_debouncer_keeps_the_latest_event_for_each_path():
    debouncer = EventDebouncer(delay_seconds=2)
    created = FileChangeEvent("created", "/tmp/notes.md", "src_1")
    modified = FileChangeEvent("modified", "/tmp/notes.md", "src_1")

    debouncer.push(created, now=0)
    debouncer.push(modified, now=1)

    assert debouncer.ready(now=2.9) == []
    assert debouncer.ready(now=3) == [modified]


def test_handler_normalizes_create_modify_delete_and_move_events(tmp_path):
    source = _source(tmp_path)
    debouncer = EventDebouncer(delay_seconds=0)
    seen = []
    handler = WatchEventHandler(
        source,
        FileScanner(),
        {".md"},
        debouncer,
        on_event=seen.append,
    )
    original = tmp_path / "original.md"
    renamed = tmp_path / "renamed.md"

    handler.on_created(FileCreatedEvent(str(original)))
    handler.on_modified(FileModifiedEvent(str(original)))
    handler.on_deleted(FileDeletedEvent(str(original)))
    handler.on_moved(FileMovedEvent(str(original), str(renamed)))
    handler.on_created(FileCreatedEvent(str(tmp_path / "secret.pem")))

    assert [(event.event_type, event.path) for event in seen] == [
        ("created", str(original)),
        ("modified", str(original)),
        ("deleted", str(original)),
        ("deleted", str(original)),
        ("created", str(renamed)),
    ]


def test_watch_jobs_map_events_and_deduplicate_pending_paths(tmp_path):
    engine, source, _ = _engine(tmp_path)
    service = WatchService(engine)
    path = str(tmp_path / "source" / "notes.md")

    service.queue_event(FileChangeEvent("created", path, source.id))
    service.queue_event(FileChangeEvent("modified", path, source.id))
    queued = engine.sqlite.claim_watch_job()

    assert queued is not None
    assert queued.job_type == "reindex_file"
    assert engine.sqlite.queued_watch_job_count() == 0


def test_delete_job_removes_file_metadata_and_vector_chunks(tmp_path):
    engine, source, lance = _engine(tmp_path)
    path = tmp_path / "source" / "old.md"
    path.write_text("old memory", encoding="utf-8")
    record = _file_record(source, path)
    engine.sqlite.upsert_file(record)
    service = WatchService(engine)
    service.queue_event(FileChangeEvent("deleted", str(path), source.id))

    completed = service.process_next_job()

    assert completed is not None and completed.status == "completed"
    assert engine.sqlite.file_by_path(str(path)) is None
    assert lance.deleted_file_ids == [record.id]


def test_failed_watch_job_does_not_block_the_next_job(tmp_path):
    engine, source, _ = _engine(tmp_path)
    first = tmp_path / "source" / "first.md"
    second = tmp_path / "source" / "second.md"
    first.write_text("first", encoding="utf-8")
    second.write_text("second", encoding="utf-8")

    class FailingOnceService(WatchService):
        def __init__(self, current_engine):
            super().__init__(current_engine, stability_interval=0, sleep=lambda _: None)
            self.failed = False

        def _index_path(self, job):
            if not self.failed:
                self.failed = True
                raise RuntimeError("broken document")
            return super()._index_path(job)

    service = FailingOnceService(engine)
    service.queue_event(FileChangeEvent("created", str(first), source.id))
    service.queue_event(FileChangeEvent("created", str(second), source.id))

    failed = service.process_next_job()
    completed = service.process_next_job()

    assert failed is not None and failed.status == "failed"
    assert completed is not None and completed.status == "completed"
    assert engine.sqlite.file_by_path(str(second)).status == "indexed"
    assert service.status().errors[0].endswith("broken document")


def test_catch_up_queues_new_changed_and_deleted_files(tmp_path):
    engine, source, _ = _engine(tmp_path)
    source_path = tmp_path / "source"
    changed = source_path / "changed.md"
    new = source_path / "new.md"
    missing = source_path / "missing.md"
    changed.write_text("new content", encoding="utf-8")
    new.write_text("new file", encoding="utf-8")
    old_changed = _file_record(source, changed)
    old_changed.size = 1
    engine.sqlite.upsert_file(old_changed)
    engine.sqlite.upsert_file(_file_record(source, missing))

    WatchService(engine)._catch_up([source])
    jobs = []
    while job := engine.sqlite.claim_watch_job():
        jobs.append((job.job_type, job.path))

    assert set(jobs) == {
        ("reindex_file", str(changed)),
        ("index_file", str(new)),
        ("delete_file", str(missing)),
    }


def test_background_start_detaches_worker_from_terminal(monkeypatch, tmp_path):
    engine, _, _ = _engine(tmp_path)
    captured = {}

    class Process:
        pid = 4321

    def fake_popen(command, **options):
        captured["command"] = command
        captured["options"] = options
        return Process()

    monkeypatch.setattr("openmind.watcher.service.subprocess.Popen", fake_popen)
    monkeypatch.setattr("openmind.watcher.service._pid_is_alive", lambda pid: True)
    service = WatchService(engine, sleep=lambda _: None)

    status = service.start_background()

    assert status.state == "starting"
    assert status.pid == 4321
    assert captured["command"][-2:] == ["watch", "worker"]
    assert captured["options"]["stdin"] == subprocess.DEVNULL
    assert captured["options"]["start_new_session"] is True


def test_idle_job_poll_does_not_request_a_sqlite_write_lock(tmp_path):
    engine, _, _ = _engine(tmp_path)
    competing_writer = sqlite3.connect(engine.paths.sqlite_path)
    competing_writer.execute("BEGIN IMMEDIATE")
    try:
        assert engine.sqlite.claim_watch_job() is None
    finally:
        competing_writer.rollback()
        competing_writer.close()


def _engine(tmp_path):
    paths = AppPaths(
        home=tmp_path / "openmind",
        config_path=tmp_path / "openmind" / "config.toml",
        sqlite_path=tmp_path / "openmind" / "openmind.sqlite",
        lancedb_path=tmp_path / "openmind" / "lancedb",
        logs_path=tmp_path / "openmind" / "logs",
    )
    sqlite = SQLiteStore(paths.sqlite_path)
    lance = RecordingLanceStore()
    engine = OpenMindEngine(
        paths=paths,
        embeddings=HashEmbeddingProvider(dimension=16),
        answer_provider=ContextOnlyAnswerProvider(),
        sqlite_store=sqlite,
        lance_store=lance,
    )
    engine.init()
    source_path = tmp_path / "source"
    source_path.mkdir()
    source = _source(source_path)
    sqlite.add_source(source)
    return engine, source, lance


def _source(path):
    return Source(
        id="src_watch",
        path=str(path),
        recursive=True,
        enabled=True,
        created_at="2026-07-22T00:00:00+00:00",
    )


def _file_record(source, path):
    stat = path.stat() if path.exists() else None
    return FileRecord(
        id=f"file_{path.stem}",
        source_id=source.id,
        path=str(path),
        name=path.name,
        extension=path.suffix,
        size=stat.st_size if stat else 1,
        modified_at=stat.st_mtime if stat else 1,
        content_hash="old-hash",
        status="indexed",
    )
