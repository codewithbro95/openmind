from openmind.core.config import OCRSettings
from openmind.extractors import default_registry
from openmind.extractors.image import ImageExtractor
from openmind.extractors.pdf import PDFExtractor, _needs_ocr
from openmind.extractors.text import MarkdownExtractor, TextExtractor
from openmind.ingestion.normalizer import normalize_text


def test_default_registry_supports_documents_but_not_code_or_html():
    extensions = default_registry().supported_extensions

    assert extensions == {".txt", ".md", ".pdf", ".docx", ".csv"}
    assert extensions.isdisjoint({".py", ".js", ".ts", ".json", ".html"})


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

    def extract_image_text(self, path):
        self.paths.append(path)
        return "Visible label: cabin map."


class FakeImageDescriptionProvider:
    model_name = "fake-vision"

    def __init__(self):
        self.calls = []

    def describe(self, path, prompt, max_new_tokens):
        self.calls.append((path, prompt, max_new_tokens))
        return "A cabin trip checklist screenshot with a map and packing notes."


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


def test_image_extractor_describes_image_without_storing_raw_bytes(tmp_path):
    from PIL import Image

    path = tmp_path / "screenshot.png"
    Image.new("RGB", (16, 8), color="white").save(path)
    provider = FakeImageDescriptionProvider()
    ocr_backend = FakeOCRBackend()

    document = ImageExtractor(
        description_provider=provider,
        ocr_backend=ocr_backend,
    ).extract(str(path))

    assert "Image description:" in document.text
    assert "cabin trip checklist" in document.text
    assert "Visible text OCR:" in document.text
    assert "Visible label" in document.text
    assert document.metadata["raw_image_stored"] is False
    assert document.metadata["file_type"] == "image"
    assert document.metadata["image_width"] == 16
    assert document.metadata["image_height"] == 8
    assert document.metadata["image_ocr_used"] is True
    assert provider.calls[0][0] == path


def test_image_extractor_indexes_safe_image_metadata(tmp_path):
    from PIL import Image
    from PIL.PngImagePlugin import PngInfo

    path = tmp_path / "screenshot.png"
    png_info = PngInfo()
    png_info.add_text("Software", "OpenMind Test Rig")
    png_info.add_text("Description", "Quarterly dashboard screenshot")
    Image.new("RGB", (20, 10), color="white").save(path, pnginfo=png_info)

    document = ImageExtractor(
        description_provider=FakeImageDescriptionProvider(),
        ocr_backend=FakeOCRBackend(),
    ).extract(str(path))

    assert document.metadata["image_format"] == "PNG"
    assert document.metadata["image_info"]["Software"] == "OpenMind Test Rig"
    assert document.metadata["image_info"]["Description"] == "Quarterly dashboard screenshot"
    assert "Image metadata:" in document.text
    assert "image_info.Software: OpenMind Test Rig" in document.text
    assert "image_info.Description: Quarterly dashboard screenshot" in document.text
