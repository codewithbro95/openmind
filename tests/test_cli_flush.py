from typer.testing import CliRunner

from openmind.cli.main import app
from openmind.core.models import FileRecord, Source
from openmind.storage.sqlite_store import SQLiteStore


def test_flush_clears_index_state_and_preserves_sources_and_config(monkeypatch, tmp_path):
    home = tmp_path / ".openmind"
    source_path = tmp_path / "docs"
    source_path.mkdir()
    user_file = source_path / "notes.md"
    user_file.write_text("Holiday notes", encoding="utf-8")
    monkeypatch.setenv("OPENMIND_HOME", str(home))
    _create_indexed_state(home, source_path, user_file)

    result = CliRunner().invoke(app, ["flush", "--yes"])

    assert result.exit_code == 0
    assert "OpenMind indexed memory flushed" in result.output
    assert "User files were not deleted" in result.output
    assert user_file.exists()
    assert (home / "config.toml").exists()
    assert (home / "lancedb").exists()
    assert not (home / "lancedb" / "chunks.lance").exists()
    assert not (home / "logs" / "index-job.log").exists()

    store = SQLiteStore(home / "openmind.sqlite")
    assert len(store.list_sources()) == 1
    assert store.status(app_home=str(home)).files == 0
    assert store.latest_index_job() is None


def test_flush_can_clear_sources(monkeypatch, tmp_path):
    home = tmp_path / ".openmind"
    source_path = tmp_path / "docs"
    source_path.mkdir()
    user_file = source_path / "notes.md"
    user_file.write_text("Holiday notes", encoding="utf-8")
    monkeypatch.setenv("OPENMIND_HOME", str(home))
    _create_indexed_state(home, source_path, user_file)

    result = CliRunner().invoke(app, ["flush", "--yes", "--include-sources"])

    assert result.exit_code == 0
    assert user_file.exists()
    assert SQLiteStore(home / "openmind.sqlite").list_sources() == []


def test_flush_dry_run_keeps_index_state(monkeypatch, tmp_path):
    home = tmp_path / ".openmind"
    source_path = tmp_path / "docs"
    source_path.mkdir()
    user_file = source_path / "notes.md"
    user_file.write_text("Holiday notes", encoding="utf-8")
    monkeypatch.setenv("OPENMIND_HOME", str(home))
    _create_indexed_state(home, source_path, user_file)

    result = CliRunner().invoke(app, ["flush", "--dry-run"])

    assert result.exit_code == 0
    assert "Dry run only" in result.output
    assert SQLiteStore(home / "openmind.sqlite").status(app_home=str(home)).files == 1
    assert (home / "lancedb" / "chunks.lance").exists()


def _create_indexed_state(home, source_path, user_file):
    home.mkdir()
    (home / "config.toml").write_text("# config\n", encoding="utf-8")
    (home / "lancedb").mkdir()
    (home / "lancedb" / "chunks.lance").write_text("vectors", encoding="utf-8")
    (home / "logs").mkdir()
    (home / "logs" / "index-job.log").write_text("logs", encoding="utf-8")

    store = SQLiteStore(home / "openmind.sqlite")
    store.initialize()
    source = Source(
        id="src_1",
        path=str(source_path),
        recursive=True,
        enabled=True,
        created_at="2026-07-05T00:00:00+00:00",
    )
    store.add_source(source)
    store.upsert_file(
        FileRecord(
            id="file_1",
            source_id=source.id,
            path=str(user_file),
            name=user_file.name,
            extension=".md",
            size=user_file.stat().st_size,
            modified_at=user_file.stat().st_mtime,
            content_hash="hash",
            status="indexed",
            indexed_at="2026-07-05T00:01:00+00:00",
        )
    )
    store.create_index_job("job_1")
