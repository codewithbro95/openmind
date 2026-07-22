from openmind.core.config import AppPaths
from openmind.core.engine import OpenMindEngine
from openmind.core.models import FileRecord, Source
from openmind.embeddings.provider import HashEmbeddingProvider
from openmind.llm.answer import ContextOnlyAnswerProvider
from openmind.storage.sqlite_store import SQLiteStore


class RecordingLanceStore:
    def __init__(self):
        self.deleted_file_ids: list[str] = []

    def initialize(self):
        pass

    def delete_file_chunks(self, file_id):
        self.deleted_file_ids.append(file_id)

    def delete_source_chunks(self, source_id):
        return 0


def test_engine_removes_old_unsupported_memory_without_deleting_user_files(tmp_path):
    source_path = tmp_path / "source"
    source_path.mkdir()
    code_path = source_path / "script.py"
    markdown_path = source_path / "README.md"
    code_path.write_text("print('keep me')", encoding="utf-8")
    markdown_path.write_text("# Keep indexed", encoding="utf-8")

    paths = AppPaths(
        home=tmp_path / "openmind",
        config_path=tmp_path / "openmind" / "config.toml",
        sqlite_path=tmp_path / "openmind" / "openmind.sqlite",
        lancedb_path=tmp_path / "openmind" / "lancedb",
        logs_path=tmp_path / "openmind" / "logs",
    )
    sqlite = SQLiteStore(paths.sqlite_path)
    sqlite.initialize()
    source = Source(
        id="src_test",
        path=str(source_path),
        created_at="2026-07-22T00:00:00+00:00",
    )
    sqlite.add_source(source)
    for file_id, path in (("file_code", code_path), ("file_markdown", markdown_path)):
        sqlite.upsert_file(
            FileRecord(
                id=file_id,
                source_id=source.id,
                path=str(path),
                name=path.name,
                extension=path.suffix,
                size=path.stat().st_size,
                modified_at=path.stat().st_mtime,
                content_hash="hash",
                status="indexed",
            )
        )

    lance = RecordingLanceStore()
    engine = OpenMindEngine(
        paths=paths,
        embeddings=HashEmbeddingProvider(),
        answer_provider=ContextOnlyAnswerProvider(),
        sqlite_store=sqlite,
        lance_store=lance,
    )

    engine.init()
    engine.init()

    assert sqlite.file_by_id("file_code") is None
    assert sqlite.file_by_id("file_markdown") is not None
    assert lance.deleted_file_ids == ["file_code"]
    assert code_path.read_text(encoding="utf-8") == "print('keep me')"
