from openmind.core.config import ExtractionSettings, OCRSettings
from openmind.extractors.base import Extractor, ExtractorRegistry
from openmind.extractors.code import CodeExtractor
from openmind.extractors.docx import DocxExtractor
from openmind.extractors.html import HtmlExtractor
from openmind.extractors.image import ImageExtractor
from openmind.extractors.pdf import PDFExtractor
from openmind.extractors.tabular import CsvExtractor, JsonExtractor
from openmind.extractors.text import MarkdownExtractor, TextExtractor


def default_registry(
    extraction_settings: ExtractionSettings | None = None,
    ocr_settings: OCRSettings | None = None,
    image_description_provider=None,
) -> ExtractorRegistry:
    settings = extraction_settings or ExtractionSettings(ocr=ocr_settings or OCRSettings())
    extractors = [
        TextExtractor(),
        MarkdownExtractor(),
        PDFExtractor(ocr_settings=settings.ocr),
        DocxExtractor(),
    ]
    if image_description_provider is not None:
        extractors.append(
            ImageExtractor(
                settings=settings.images,
                description_provider=image_description_provider,
            )
        )
    extractors.extend(
        [
            CodeExtractor(),
            JsonExtractor(),
            CsvExtractor(),
            HtmlExtractor(),
        ]
    )
    return ExtractorRegistry(
        extractors
    )


__all__ = [
    "Extractor",
    "ExtractorRegistry",
    "ImageExtractor",
    "default_registry",
]
