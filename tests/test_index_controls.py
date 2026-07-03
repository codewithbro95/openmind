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
