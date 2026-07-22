from __future__ import annotations

import hashlib
from pathlib import Path

from openmind.core.models import FileRecord, Source

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
    ".build",
    "target",
    "coverage",
    ".next",
    ".nuxt",
    ".turbo",
    ".svelte-kit",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "DerivedData",
    "Assets.xcassets",
}

IGNORED_FILE_NAMES = {
    ".DS_Store",
    "Thumbs.db",
    ".env",
    "id_rsa",
    "id_ed25519",
}

IGNORED_FILE_SUFFIXES = {
    ".tmp",
    ".part",
    ".crdownload",
    ".swp",
    ".pem",
    ".key",
    ".p12",
    ".sqlite",
    ".db",
}


class FileScanner:
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
        if not file_path.is_file() or not self.is_supported_path(file_path, root, extensions):
            return None
        stat = file_path.stat()
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
    ) -> bool:
        file_path = Path(path)
        extensions = supported_extensions or SUPPORTED_EXTENSIONS
        return (
            file_path.suffix.lower() in extensions
            and not self.should_ignore(file_path, Path(root))
        )

    def should_ignore(self, path: Path, root: Path) -> bool:
        try:
            relative_parts = path.relative_to(root).parts
        except ValueError:
            return True
        for part in relative_parts:
            if part in IGNORED_DIRS:
                return True
            if part.startswith("."):
                return True
        if path.name in IGNORED_FILE_NAMES or path.name.startswith("~$"):
            return True
        if path.suffix.lower() in IGNORED_FILE_SUFFIXES:
            return True
        return False

    def content_hash(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()
