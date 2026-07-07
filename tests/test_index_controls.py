from openmind.core.config import AppPaths
from openmind.core.engine import OpenMindEngine
from openmind.core.models import FileRecord, IndexSummary


def test_worker_remains_paused_until_resume(tmp_path, monkeypatch):
    paths = AppPaths(
        home=tmp_path,
        config_path=tmp_path / "config.toml",
        sqlite_path=tmp_path / "openmind.sqlite",
        lancedb_path=tmp_path / "lancedb",
        logs_path=tmp_path / "logs",
    )
    engine = OpenMindEngine(paths=paths)
    engine.init()
    job = engine.create_index_job()

    records = [
        FileRecord(
            id="file_1",
            source_id="src_1",
            path="/tmp/one.txt",
            name="one.txt",
            extension=".txt",
            size=1,
            modified_at=1.0,
            content_hash="hash_1",
        ),
        FileRecord(
            id="file_2",
            source_id="src_1",
            path="/tmp/two.txt",
            name="two.txt",
            extension=".txt",
            size=1,
            modified_at=1.0,
            content_hash="hash_2",
        ),
    ]
    calls = {"indexed": 0, "sleep": 0}

    def fake_discover_files():
        return records

    def fake_index_file(file_record):
        calls["indexed"] += 1
        if calls["indexed"] == 1:
            engine.sqlite.update_index_job(job.id, status="pause_requested")
        return IndexSummary(files_indexed=1, chunks_created=1)

    def fake_sleep(seconds):
        calls["sleep"] += 1
        assert engine.sqlite.get_index_job(job.id).status == "paused"
        engine.sqlite.update_index_job(job.id, status="running")

    monkeypatch.setattr(engine, "discover_files", fake_discover_files)
    monkeypatch.setattr(engine, "_index_file", fake_index_file)
    monkeypatch.setattr("openmind.core.engine.time.sleep", fake_sleep)

    final_job = engine.run_index_worker(job.id)

    assert calls == {"indexed": 2, "sleep": 1}
    assert final_job.status == "completed"
    assert final_job.processed_files == 2


def test_index_file_reports_already_indexed_file(tmp_path):
    paths = AppPaths(
        home=tmp_path,
        config_path=tmp_path / "config.toml",
        sqlite_path=tmp_path / "openmind.sqlite",
        lancedb_path=tmp_path / "lancedb",
        logs_path=tmp_path / "logs",
    )
    engine = OpenMindEngine(paths=paths)
    engine.init()
    record = FileRecord(
        id="file_1",
        source_id="src_1",
        path=str(tmp_path / "notes.md"),
        name="notes.md",
        extension=".md",
        size=12,
        modified_at=1.0,
        content_hash="same-hash",
        status="indexed",
        indexed_at="2026-07-05T00:00:00+00:00",
    )
    engine.sqlite.upsert_file(record)

    summary = engine._index_file(
        record.model_copy(update={"id": "file_2", "status": "pending", "indexed_at": None})
    )

    assert summary.files_skipped == 1
    assert summary.files_already_indexed == 1
    assert summary.files_indexed == 0


def test_index_file_skips_unchanged_indexed_file_without_hashing(tmp_path, monkeypatch):
    paths = AppPaths(
        home=tmp_path,
        config_path=tmp_path / "config.toml",
        sqlite_path=tmp_path / "openmind.sqlite",
        lancedb_path=tmp_path / "lancedb",
        logs_path=tmp_path / "logs",
    )
    engine = OpenMindEngine(paths=paths)
    engine.init()
    file_path = tmp_path / "notes.md"
    file_path.write_text("Holiday planning notes", encoding="utf-8")
    stat = file_path.stat()
    record = FileRecord(
        id="file_1",
        source_id="src_1",
        path=str(file_path),
        name="notes.md",
        extension=".md",
        size=stat.st_size,
        modified_at=stat.st_mtime,
        content_hash="existing-hash",
        status="indexed",
        indexed_at="2026-07-05T00:00:00+00:00",
    )
    engine.sqlite.upsert_file(record)

    def fail_content_hash(path):
        raise AssertionError("unchanged indexed files should not be hashed again")

    monkeypatch.setattr(engine.scanner, "content_hash", fail_content_hash)

    summary = engine._index_file(
        record.model_copy(update={"content_hash": "", "status": "pending", "indexed_at": None})
    )

    assert summary.files_skipped == 1
    assert summary.files_already_indexed == 1
