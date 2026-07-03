from __future__ import annotations

from pathlib import Path

from openmind.core.models import ExtractedDocument
from openmind.extractors.base import Extractor


class PDFExtractor(Extractor):
    extensions = {".pdf"}

    def extract(self, path: str) -> ExtractedDocument:
        from pypdf import PdfReader

        file_path = Path(path)
        reader = PdfReader(str(file_path))
        pages: list[str] = []
        for index, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            if text.strip():
                pages.append(f"\n\n[Page {index}]\n{text}")
        return ExtractedDocument(
            file_path=str(file_path),
            title=file_path.stem,
            text="\n".join(pages).strip(),
            metadata={"extension": ".pdf", "page_count": len(reader.pages)},
        )
