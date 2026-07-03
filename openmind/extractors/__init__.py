from openmind.extractors.base import Extractor, ExtractorRegistry
from openmind.extractors.code import CodeExtractor
from openmind.extractors.docx import DocxExtractor
from openmind.extractors.html import HtmlExtractor
from openmind.extractors.pdf import PDFExtractor
from openmind.extractors.tabular import CsvExtractor, JsonExtractor
from openmind.extractors.text import MarkdownExtractor, TextExtractor


def default_registry() -> ExtractorRegistry:
    return ExtractorRegistry(
        [
            TextExtractor(),
            MarkdownExtractor(),
            PDFExtractor(),
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
