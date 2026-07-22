import pytest

from openmind.core.config import AppPaths
from openmind.core.engine import OpenMindEngine
from openmind.core.errors import SourceRemovalBlockedError
from openmind.embeddings.provider import HashEmbeddingProvider


def test_remove_source_deletes_its_memory_and_keeps_user_files(tmp_path):
    engine = _engine(tmp_path)
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    first_dir.mkdir()
    second_dir.mkdir()
    first_file = first_dir / "first.md"
    second_file = second_dir / "second.md"
    first_file.write_text("First holiday checklist", encoding="utf-8")
    second_file.write_text("Second project notes", encoding="utf-8")
    first_source = engine.add_source(str(first_dir))
    second_source = engine.add_source(str(second_dir))

    indexed = engine.index()
    first_record = engine.sqlite.file_by_path(str(first_file))
    second_record = engine.sqlite.file_by_path(str(second_file))

    assert indexed.files_indexed == 2
    assert engine.lance.count_chunks() == 2

    result = engine.remove_source(first_source.id)

    assert result is not None
    assert result.source_id == first_source.id
    assert result.files_removed == 1
    assert result.chunks_removed == 1
    assert engine.sources.get(first_source.id) is None
    assert engine.sources.get(second_source.id) is not None
    assert engine.sqlite.file_by_id(first_record.id) is None
    assert engine.sqlite.file_by_id(second_record.id) is not None
    assert engine.lance.chunks_for_file(first_record.id) == []
    assert engine.lance.chunks_for_file(second_record.id)
    assert engine.lance.count_chunks() == 1
    assert first_file.exists()
    assert second_file.exists()


def test_remove_source_is_blocked_during_active_indexing(tmp_path):
    engine = _engine(tmp_path)
    source_dir = tmp_path / "docs"
    source_dir.mkdir()
    source = engine.add_source(str(source_dir))
    job = engine.sqlite.create_index_job("job_active")
    engine.sqlite.update_index_job(job.id, status="stop_requested")

    with pytest.raises(SourceRemovalBlockedError, match="Stop indexing first"):
        engine.remove_source(source.id)

    assert engine.sources.get(source.id) is not None


def test_remove_source_is_blocked_while_watch_mode_is_active(tmp_path):
    engine = _engine(tmp_path)
    source_dir = tmp_path / "docs"
    source_dir.mkdir()
    source = engine.add_source(str(source_dir))
    engine.sqlite.update_watch_state(status="running", pid=1234)

    with pytest.raises(SourceRemovalBlockedError, match="openmind watch stop"):
        engine.remove_source(source.id)

    assert engine.sources.get(source.id) is not None


def test_init_cleans_memory_left_by_legacy_source_removal(tmp_path):
    engine = _engine(tmp_path)
    source_dir = tmp_path / "legacy"
    source_dir.mkdir()
    user_file = source_dir / "legacy.md"
    user_file.write_text("Legacy indexed notes", encoding="utf-8")
    source = engine.add_source(str(source_dir))
    engine.index()
    record = engine.sqlite.file_by_path(str(user_file))

    with engine.sqlite.connect() as conn:
        conn.execute("DELETE FROM sources WHERE id = ?", (source.id,))

    assert engine.lance.count_chunks() == 1
    assert engine.sqlite.file_by_id(record.id) is not None

    engine.init()

    assert engine.lance.count_chunks() == 0
    assert engine.sqlite.file_by_id(record.id) is None
    assert user_file.exists()


def _engine(tmp_path):
    home = tmp_path / ".openmind"
    return OpenMindEngine(
        paths=AppPaths(
            home=home,
            config_path=home / "config.toml",
            sqlite_path=home / "openmind.sqlite",
            lancedb_path=home / "lancedb",
            logs_path=home / "logs",
        ),
        embeddings=HashEmbeddingProvider(dimension=16),
    )
