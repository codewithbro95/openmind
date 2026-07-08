from openmind.core.config import OCRSettings
from openmind.extractors.base import Extractor, ExtractorRegistry
from openmind.extractors.code import CodeExtractor
from openmind.extractors.docx import DocxExtractor
from openmind.extractors.html import HtmlExtractor
from openmind.extractors.pdf import PDFExtractor
from openmind.extractors.tabular import CsvExtractor, JsonExtractor
from openmind.extractors.text import MarkdownExtractor, TextExtractor


def default_registry(ocr_settings: OCRSettings | None = None) -> ExtractorRegistry:
    return ExtractorRegistry(
        [
            TextExtractor(),
            MarkdownExtractor(),
            PDFExtractor(ocr_settings=ocr_settings),
            DocxExtractor(),
            CodeExtractor(),
            JsonExtractor(),
            CsvExtractor(),
            HtmlExtractor(),
        ]
    )


__all__ = [
    "Extractor",
    "ExtractorRegistry",
    "default_registry",
]
