from openmind.extractors.text import MarkdownExtractor, TextExtractor
from openmind.ingestion.normalizer import normalize_text


def test_text_extractor_returns_plain_text(tmp_path):
    path = tmp_path / "note.txt"
    path.write_text("hello\nworld", encoding="utf-8")

    document = TextExtractor().extract(str(path))

    assert document.title == "note"
    assert document.text == "hello\nworld"
    assert document.metadata["extension"] == ".txt"


def test_markdown_extractor_supports_md(tmp_path):
    path = tmp_path / "note.md"
    path.write_text("# Title", encoding="utf-8")

    assert MarkdownExtractor().supports(str(path))


def test_normalizer_collapses_noise():
    assert normalize_text("a   b\n\n\nc\r\nd") == "a b\n\nc\nd"
