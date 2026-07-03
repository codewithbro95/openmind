from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from openmind.core.models import ExtractedDocument


class Extractor(ABC):
    extensions: set[str] = set()

    def supports(self, path: str) -> bool:
        return Path(path).suffix.lower() in self.extensions

    @abstractmethod
    def extract(self, path: str) -> ExtractedDocument:
        raise NotImplementedError


class ExtractorRegistry:
    def __init__(self, extractors: list[Extractor]):
        self.extractors = extractors

    def for_path(self, path: str) -> Extractor:
        for extractor in self.extractors:
            if extractor.supports(path):
                return extractor
        raise ValueError(f"No extractor supports: {path}")
