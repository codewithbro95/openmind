from openmind.core.models import FileRecord, Source
from openmind.storage.sqlite_store import SQLiteStore


def test_sqlite_store_initializes_sources_and_files(tmp_path):
    store = SQLiteStore(tmp_path / "openmind.sqlite")
    store.initialize()

    source = Source(
        id="src_1",
        path=str(tmp_path),
        recursive=True,
        enabled=True,
        created_at="2026-01-01T00:00:00+00:00",
    )
    store.add_source(source)

    file_record = FileRecord(
        id="file_1",
        source_id="src_1",
        path=str(tmp_path / "notes.md"),
        name="notes.md",
        extension=".md",
        size=12,
        modified_at=1.0,
        content_hash="hash",
        status="indexed",
        indexed_at="2026-01-01T00:01:00+00:00",
    )
    store.upsert_file(file_record)

    assert store.list_sources() == [source]
    assert store.file_by_path(str(tmp_path / "notes.md")).status == "indexed"
    assert store.status(app_home=str(tmp_path)).indexed_files == 1
