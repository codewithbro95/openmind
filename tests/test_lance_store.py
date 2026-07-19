from openmind.core.models import Chunk
from openmind.storage.lance_store import LanceStore


def test_lance_store_counts_and_returns_sanitized_file_chunks(tmp_path):
    store = LanceStore(tmp_path / "lancedb")
    chunk = Chunk(
        id="chunk_1",
        document_id="doc_1",
        source_id="src_0123456789ab",
        file_id="file_0123456789abcdef",
        path="/docs/holiday.md",
        file_name="holiday.md",
        extension=".md",
        title="Holiday",
        text="Cabin packing notes",
        chunk_index=0,
        content_hash="hash",
        modified_at=1.0,
        metadata={"extension": ".md"},
    )

    store.add_chunks([chunk], [[0.1, 0.2, 0.3]])
    chunks = store.chunks_for_file(chunk.file_id)

    assert store.count_chunks() == 1
    assert chunks == [
        {
            "id": "chunk_1",
            "text": "Cabin packing notes",
            "chunk_index": 0,
            "title": "Holiday",
            "metadata": {"extension": ".md"},
        }
    ]
    assert "vector" not in chunks[0]


def test_lance_store_deletes_only_chunks_for_selected_source(tmp_path):
    store = LanceStore(tmp_path / "lancedb")
    first = _chunk("chunk_1", "src_first", "file_0123456789abcdef", "First source")
    second = _chunk("chunk_2", "src_second", "file_fedcba9876543210", "Second source")
    store.add_chunks([first, second], [[0.1, 0.2], [0.2, 0.1]])

    removed = store.delete_source_chunks(first.source_id)

    assert removed == 1
    assert store.count_chunks() == 1
    assert store.chunks_for_file(first.file_id) == []
    assert store.chunks_for_file(second.file_id)[0]["text"] == "Second source"


def _chunk(chunk_id, source_id, file_id, text):
    return Chunk(
        id=chunk_id,
        document_id=f"doc_{chunk_id}",
        source_id=source_id,
        file_id=file_id,
        path=f"/docs/{file_id}.md",
        file_name=f"{file_id}.md",
        extension=".md",
        title=text,
        text=text,
        chunk_index=0,
        content_hash=f"hash_{chunk_id}",
        modified_at=1.0,
        metadata={"extension": ".md"},
    )
