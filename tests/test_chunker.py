from openmind.core.models import Document, FileRecord
from openmind.ingestion.chunker import TextChunker


def test_chunker_creates_overlapping_chunks():
    document = Document(
        id="doc_1",
        source_id="src_1",
        path="/tmp/example.txt",
        title="example",
        text="abcdef" * 20,
        metadata={"extension": ".txt"},
    )
    file_record = FileRecord(
        id="file_1",
        source_id="src_1",
        path="/tmp/example.txt",
        name="example.txt",
        extension=".txt",
        size=120,
        modified_at=1.0,
        content_hash="hash",
    )

    chunks = TextChunker(chunk_size=30, overlap=10).chunk(document, file_record)

    assert len(chunks) > 1
    assert chunks[0].text[-10:] == chunks[1].text[:10]
    assert chunks[0].path == "/tmp/example.txt"
    assert chunks[0].metadata["extension"] == ".txt"
