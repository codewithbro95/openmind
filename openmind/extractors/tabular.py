from __future__ import annotations

from pathlib import Path

from openmind.core.models import ExtractedDocument
from openmind.extractors.base import Extractor


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
