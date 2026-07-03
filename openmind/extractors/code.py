from __future__ import annotations

from pathlib import Path

from openmind.core.models import ExtractedDocument
from openmind.extractors.base import Extractor


class CodeExtractor(Extractor):
    extensions = {".py", ".js", ".ts"}

    def extract(self, path: str) -> ExtractedDocument:
        file_path = Path(path)
        text = file_path.read_text(encoding="utf-8", errors="replace")
        return ExtractedDocument(
            file_path=str(file_path),
            title=file_path.name,
            text=text,
            metadata={"extension": file_path.suffix.lower(), "kind": "code"},
        )
