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
