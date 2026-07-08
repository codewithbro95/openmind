from openmind.core.config import OCRSettings
from openmind.extractors.pdf import PDFExtractor, _needs_ocr
from openmind.extractors.text import MarkdownExtractor, TextExtractor
from openmind.ingestion.normalizer import normalize_text


class FakePDFPage:
    def __init__(self, text):
        self.text = text

    def extract_text(self):
        return self.text


class FakePDFReader:
    def __init__(self, path):
        self.pages = [FakePDFPage("")]


class FakeOCRBackend:
    name = "fake-ocr"

    def __init__(self):
        self.paths = []

    def extract_pdf_text(self, path):
        self.paths.append(path)
        return "OCR extracted invoice text with order ID 12345."


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


def test_pdf_extractor_uses_ocr_when_normal_extraction_is_weak(monkeypatch, tmp_path):
    import pypdf

    monkeypatch.setattr(pypdf, "PdfReader", FakePDFReader)
    path = tmp_path / "scan.pdf"
    path.write_bytes(b"%PDF fake")
    backend = FakeOCRBackend()

    document = PDFExtractor(ocr_backend=backend).extract(str(path))

    assert document.text == "OCR extracted invoice text with order ID 12345."
    assert backend.paths == [path]
    assert document.metadata["extraction_method"] == "ocr"
    assert document.metadata["ocr_used"] is True
    assert document.metadata["ocr_engine"] == "fake-ocr"
    assert document.metadata["normal_extraction_chars"] == 0


def test_pdf_extractor_records_disabled_ocr_when_text_is_weak(monkeypatch, tmp_path):
    import pypdf

    monkeypatch.setattr(pypdf, "PdfReader", FakePDFReader)
    path = tmp_path / "scan.pdf"
    path.write_bytes(b"%PDF fake")

    document = PDFExtractor(ocr_settings=OCRSettings(enabled=False)).extract(str(path))

    assert document.text == ""
    assert document.metadata["extraction_method"] == "pypdf"
    assert document.metadata["ocr_used"] is False
    assert document.metadata["ocr_attempted"] is True
    assert "disabled" in document.metadata["ocr_error"]


def test_needs_ocr_for_sparse_pdf_text():
    settings = OCRSettings(min_text_chars_per_page=80)

    assert _needs_ocr("", page_count=3, settings=settings) is True
    assert _needs_ocr("short text", page_count=3, settings=settings) is True
    assert _needs_ocr("normal text " * 100, page_count=3, settings=settings) is False
