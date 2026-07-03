from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Source(BaseModel):
    id: str
    path: str
    recursive: bool = True
    enabled: bool = True
    created_at: str


class FileRecord(BaseModel):
    id: str
    source_id: str
    path: str
    name: str
    extension: str
    size: int
    modified_at: float
    content_hash: str
    status: str = "pending"
    indexed_at: str | None = None
    error: str | None = None


class ExtractedDocument(BaseModel):
    file_path: str
    title: str
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class Document(BaseModel):
    id: str
    source_id: str
    path: str
    title: str
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class Chunk(BaseModel):
    id: str
    document_id: str
    source_id: str
    file_id: str
    path: str
    file_name: str
    extension: str
    title: str
    text: str
    chunk_index: int
    content_hash: str
    modified_at: float
    metadata: dict[str, Any] = Field(default_factory=dict)


class SearchResult(BaseModel):
    id: str
    path: str
    file_name: str
    title: str
    text: str
    snippet: str
    score: float
    chunk_index: int
    metadata: dict[str, Any] = Field(default_factory=dict)


class IndexSummary(BaseModel):
    files_seen: int = 0
    files_indexed: int = 0
    files_skipped: int = 0
    errors: int = 0


class StatusSummary(BaseModel):
    sources: int
    enabled_sources: int
    files: int
    indexed_files: int
    app_home: str
