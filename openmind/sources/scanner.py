from __future__ import annotations

import hashlib
from pathlib import Path

from openmind.core.models import FileRecord, Source
from openmind.ignore.engine import IgnoreEngine
from openmind.ignore.models import IgnoreDecision

SUPPORTED_EXTENSIONS = {
    ".txt",
    ".md",
    ".pdf",
    ".docx",
    ".csv",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".bmp",
    ".tif",
    ".tiff",
}

class FileScanner:
    def __init__(self, ignore_engine: IgnoreEngine | None = None):
        self.ignore_engine = ignore_engine or IgnoreEngine()

    def scan(
        self,
        source: Source,
        include_content_hash: bool = True,
        supported_extensions: set[str] | None = None,
    ) -> list[FileRecord]:
        root = Path(source.path)
        if not root.exists():
            return []
        extensions = supported_extensions or SUPPORTED_EXTENSIONS
        paths = root.rglob("*") if source.recursive else root.glob("*")
        records: list[FileRecord] = []
        for path in paths:
            record = self.record_for_path(
                source,
                path,
                include_content_hash=include_content_hash,
                supported_extensions=extensions,
            )
            if record is None:
                continue
            records.append(record)
        return records

    def record_for_path(
        self,
        source: Source,
        path: str | Path,
        *,
        include_content_hash: bool = False,
        supported_extensions: set[str] | None = None,
    ) -> FileRecord | None:
        file_path = Path(path)
        root = Path(source.path)
        extensions = supported_extensions or SUPPORTED_EXTENSIONS
        if not file_path.is_file():
            return None
        stat = file_path.stat()
        if not self.is_supported_path(
            file_path,
            root,
            extensions,
            source_id=source.id,
            metadata={"size": stat.st_size},
        ):
            return None
        return FileRecord(
            id=f"file_{hashlib.sha1(str(file_path).encode('utf-8')).hexdigest()[:16]}",
            source_id=source.id,
            path=str(file_path),
            name=file_path.name,
            extension=file_path.suffix.lower(),
            size=stat.st_size,
            modified_at=stat.st_mtime,
            content_hash=self.content_hash(file_path) if include_content_hash else "",
            status="pending",
        )

    def is_supported_path(
        self,
        path: str | Path,
        root: str | Path,
        supported_extensions: set[str] | None = None,
        *,
        source_id: str | None = None,
        metadata: dict | None = None,
    ) -> bool:
        file_path = Path(path).expanduser().resolve(strict=False)
        root_path = Path(root).expanduser().resolve(strict=False)
        extensions = supported_extensions or SUPPORTED_EXTENSIONS
        return bool(
            file_path.suffix.lower() in extensions
            and _is_within(file_path, root_path)
            and not self.should_ignore(
                file_path,
                root_path,
                source_id=source_id,
                metadata=metadata,
            )
        )

    def should_ignore(
        self,
        path: str | Path,
        root: str | Path,
        *,
        source_id: str | None = None,
        metadata: dict | None = None,
    ) -> bool:
        file_path = Path(path).expanduser().resolve(strict=False)
        root_path = Path(root).expanduser().resolve(strict=False)
        if not _is_within(file_path, root_path):
            return True
        return self.ignore_decision(file_path, source_id, metadata).ignored

    def ignore_decision(
        self,
        path: str | Path,
        source_id: str | None = None,
        metadata: dict | None = None,
    ) -> IgnoreDecision:
        return self.ignore_engine.should_ignore(path, source_id=source_id, metadata=metadata)

    def content_hash(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
