from __future__ import annotations

import hashlib
from pathlib import Path

from openmind.core.models import FileRecord, Source

SUPPORTED_EXTENSIONS = {
    ".txt",
    ".md",
    ".pdf",
    ".docx",
    ".py",
    ".js",
    ".ts",
    ".json",
    ".csv",
    ".html",
}

IGNORED_DIRS = {
    ".git",
    "node_modules",
    "venv",
    ".venv",
    ".env",
    "__pycache__",
    "dist",
    "build",
    ".cache",
}


class FileScanner:
    def scan(self, source: Source) -> list[FileRecord]:
        root = Path(source.path)
        if not root.exists():
            return []
        paths = root.rglob("*") if source.recursive else root.glob("*")
        records: list[FileRecord] = []
        for path in paths:
            if self._should_ignore(path, root) or not path.is_file():
                continue
            extension = path.suffix.lower()
            if extension not in SUPPORTED_EXTENSIONS:
                continue
            stat = path.stat()
            records.append(
                FileRecord(
                    id=f"file_{hashlib.sha1(str(path).encode('utf-8')).hexdigest()[:16]}",
                    source_id=source.id,
                    path=str(path),
                    name=path.name,
                    extension=extension,
                    size=stat.st_size,
                    modified_at=stat.st_mtime,
                    content_hash=self.content_hash(path),
                    status="pending",
                )
            )
        return records

    def _should_ignore(self, path: Path, root: Path) -> bool:
        try:
            relative_parts = path.relative_to(root).parts
        except ValueError:
            relative_parts = path.parts
        for part in relative_parts:
            if part in IGNORED_DIRS:
                return True
            if part.startswith(".") and part not in {".html"}:
                return True
        return False

    def content_hash(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()
