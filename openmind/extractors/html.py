from __future__ import annotations

from pathlib import Path

from openmind.core.models import ExtractedDocument
from openmind.extractors.base import Extractor


class HtmlExtractor(Extractor):
    extensions = {".html"}

    def extract(self, path: str) -> ExtractedDocument:
        from bs4 import BeautifulSoup

        file_path = Path(path)
        html = file_path.read_text(encoding="utf-8", errors="replace")
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        title = soup.title.string.strip() if soup.title and soup.title.string else file_path.stem
        text = soup.get_text(separator="\n")
        return ExtractedDocument(
            file_path=str(file_path),
            title=title,
            text=text,
            metadata={"extension": ".html"},
        )
