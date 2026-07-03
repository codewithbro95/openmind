from __future__ import annotations

import json
from pathlib import Path

from openmind.core.models import ExtractedDocument
from openmind.extractors.base import Extractor


class JsonExtractor(Extractor):
    extensions = {".json"}

    def extract(self, path: str) -> ExtractedDocument:
        file_path = Path(path)
        raw = file_path.read_text(encoding="utf-8", errors="replace")
        try:
            parsed = json.loads(raw)
            text = json.dumps(parsed, indent=2, ensure_ascii=True)
        except json.JSONDecodeError:
            text = raw
        return ExtractedDocument(
            file_path=str(file_path),
            title=file_path.name,
            text=text,
            metadata={"extension": ".json", "kind": "json"},
        )


class CsvExtractor(Extractor):
    extensions = {".csv"}

    def extract(self, path: str) -> ExtractedDocument:
        import pandas as pd

        file_path = Path(path)
        dataframe = pd.read_csv(file_path)
        text = dataframe.to_csv(index=False)
        return ExtractedDocument(
            file_path=str(file_path),
            title=file_path.name,
            text=text,
            metadata={
                "extension": ".csv",
                "kind": "csv",
                "rows": int(dataframe.shape[0]),
                "columns": int(dataframe.shape[1]),
            },
        )
