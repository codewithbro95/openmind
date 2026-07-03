from __future__ import annotations

import uuid

from openmind.core.models import Chunk, Document, FileRecord


class TextChunker:
    def __init__(self, chunk_size: int = 3000, overlap: int = 400):
        if overlap >= chunk_size:
            raise ValueError("overlap must be smaller than chunk_size")
        self.chunk_size = chunk_size
        self.overlap = overlap

    def chunk(self, document: Document, file_record: FileRecord) -> list[Chunk]:
        text = document.text.strip()
        if not text:
            return []
        chunks: list[Chunk] = []
        start = 0
        index = 0
        while start < len(text):
            end = min(start + self.chunk_size, len(text))
            chunk_text = text[start:end].strip()
            if chunk_text:
                chunks.append(
                    Chunk(
                        id=f"chunk_{uuid.uuid4().hex}",
                        document_id=document.id,
                        source_id=document.source_id,
                        file_id=file_record.id,
                        path=document.path,
                        file_name=file_record.name,
                        extension=file_record.extension,
                        title=document.title,
                        text=chunk_text,
                        chunk_index=index,
                        content_hash=file_record.content_hash,
                        modified_at=file_record.modified_at,
                        metadata={**document.metadata, "chunk_start": start, "chunk_end": end},
                    )
                )
                index += 1
            if end == len(text):
                break
            start = max(0, end - self.overlap)
        return chunks
