from __future__ import annotations

from pathlib import Path

from openmind.core.config import OCRSettings
from openmind.core.models import ExtractedDocument
from openmind.extractors.base import Extractor
from openmind.extractors.ocr import (
    OCRExtractionError,
    OCRUnavailableError,
    OCRmyPDFBackend,
    RapidOCRBackend,
)


class PDFExtractor(Extractor):
    extensions = {".pdf"}

    def __init__(
        self,
        ocr_settings: OCRSettings | None = None,
        ocr_backend: RapidOCRBackend | OCRmyPDFBackend | None = None,
    ):
        self.ocr_settings = ocr_settings or OCRSettings()
        self.ocr_backend = ocr_backend or _ocr_backend_for(self.ocr_settings.backend)

    def extract(self, path: str) -> ExtractedDocument:
        from pypdf import PdfReader

        file_path = Path(path)
        reader = PdfReader(str(file_path))
        pages: list[str] = []
        for index, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            if text.strip():
                pages.append(f"\n\n[Page {index}]\n{text}")
        text = "\n".join(pages).strip()
        metadata = {
            "extension": ".pdf",
            "file_type": "pdf",
            "page_count": len(reader.pages),
            "extraction_method": "pypdf",
            "ocr_used": False,
        }
        if _needs_ocr(text, page_count=len(reader.pages), settings=self.ocr_settings):
            metadata.update(
                {
                    "normal_extraction_chars": len(text),
                    "ocr_attempted": True,
                }
            )
            if self.ocr_settings.enabled and self.ocr_settings.backend in {"rapidocr", "ocrmypdf"}:
                try:
                    ocr_text = self.ocr_backend.extract_pdf_text(file_path)
                except (OCRUnavailableError, OCRExtractionError) as exc:
                    metadata["ocr_error"] = str(exc)
                else:
                    if ocr_text.strip():
                        text = ocr_text
                        metadata.update(
                            {
                                "extraction_method": "ocr",
                                "ocr_engine": self.ocr_backend.name,
                                "ocr_used": True,
                                "ocr_chars": len(text),
                            }
                        )
                    else:
                        metadata["ocr_error"] = "OCR completed but returned no text."
            elif self.ocr_settings.enabled:
                metadata["ocr_error"] = (
                    f"Unsupported OCR backend: {self.ocr_settings.backend}. "
                    "Supported backends: rapidocr, ocrmypdf."
                )
            else:
                metadata["ocr_error"] = "OCR fallback is disabled in config."

        return ExtractedDocument(
            file_path=str(file_path),
            title=file_path.stem,
            text=text,
            metadata=metadata,
        )


def _needs_ocr(text: str, page_count: int, settings: OCRSettings) -> bool:
    if page_count <= 0:
        return False
    stripped = text.strip()
    if not stripped:
        return True
    if len(stripped) < settings.min_text_chars_per_page * page_count:
        return True
    return _weird_character_ratio(stripped) > 0.25


def _weird_character_ratio(text: str) -> float:
    if not text:
        return 0.0
    weird = 0
    for char in text:
        if char.isalnum() or char.isspace() or char in ".,;:!?()[]{}'\"-/\\@#$%&*+=<>|_`~^":
            continue
        weird += 1
    return weird / len(text)


def _ocr_backend_for(name: str):
    if name == "ocrmypdf":
        return OCRmyPDFBackend()
    return RapidOCRBackend()
