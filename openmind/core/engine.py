from __future__ import annotations

import uuid

from openmind.core.config import AppPaths
from openmind.core.models import Document, IndexSummary, SearchResult, Source, StatusSummary
from openmind.embeddings.provider import EmbeddingProvider, SentenceTransformerEmbeddingProvider
from openmind.extractors import ExtractorRegistry, default_registry
from openmind.ingestion.chunker import TextChunker
from openmind.ingestion.normalizer import normalize_text
from openmind.llm.answer import AnswerProvider, ContextOnlyAnswerProvider
from openmind.retrieval.search import SearchService
from openmind.sources.manager import SourceManager
from openmind.sources.scanner import FileScanner
from openmind.storage.lance_store import LanceStore
from openmind.storage.sqlite_store import SQLiteStore, utc_now


class OpenMindEngine:
    def __init__(
        self,
        paths: AppPaths | None = None,
        embeddings: EmbeddingProvider | None = None,
        answer_provider: AnswerProvider | None = None,
        extractors: ExtractorRegistry | None = None,
        sqlite_store: SQLiteStore | None = None,
        lance_store: LanceStore | None = None,
    ):
        self.paths = paths or AppPaths.from_env()
        self.sqlite = sqlite_store or SQLiteStore(self.paths.sqlite_path)
        self.lance = lance_store or LanceStore(self.paths.lancedb_path)
        self.sources = SourceManager(self.sqlite)
        self.scanner = FileScanner()
        self.extractors = extractors or default_registry()
        self.chunker = TextChunker()
        self.embeddings = embeddings or SentenceTransformerEmbeddingProvider()
        self.answer_provider = answer_provider or ContextOnlyAnswerProvider()

    def init(self) -> AppPaths:
        self.paths.ensure()
        self.sqlite.initialize()
        self.lance.initialize()
        return self.paths

    def add_source(self, path: str) -> Source:
        self.init()
        return self.sources.add(path)

    def list_sources(self) -> list[Source]:
        self.init()
        return self.sources.list()

    def remove_source(self, source_id: str) -> bool:
        self.init()
        return self.sources.remove(source_id)

    def index(self) -> IndexSummary:
        self.init()
        summary = IndexSummary()
        for source in self.sources.list(enabled_only=True):
            for file_record in self.scanner.scan(source):
                summary.files_seen += 1
                existing = self.sqlite.file_by_path(file_record.path)
                if (
                    existing
                    and existing.content_hash == file_record.content_hash
                    and existing.status == "indexed"
                ):
                    summary.files_skipped += 1
                    continue

                try:
                    extractor = self.extractors.for_path(file_record.path)
                    extracted = extractor.extract(file_record.path)
                    text = normalize_text(extracted.text)
                    if not text:
                        file_record.status = "skipped"
                        file_record.error = "No text extracted"
                        self.sqlite.upsert_file(file_record)
                        summary.files_skipped += 1
                        continue

                    document = Document(
                        id=f"doc_{uuid.uuid4().hex}",
                        source_id=source.id,
                        path=file_record.path,
                        title=extracted.title,
                        text=text,
                        metadata=extracted.metadata,
                    )
                    chunks = self.chunker.chunk(document, file_record)
                    vectors = self.embeddings.embed([chunk.text for chunk in chunks])
                    self.lance.delete_file_chunks(file_record.id)
                    self.lance.add_chunks(chunks, vectors)

                    file_record.status = "indexed"
                    file_record.indexed_at = utc_now()
                    self.sqlite.upsert_file(file_record)
                    summary.files_indexed += 1
                except Exception as exc:
                    file_record.status = "error"
                    file_record.error = str(exc)
                    self.sqlite.upsert_file(file_record)
                    summary.errors += 1
        return summary

    def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        self.init()
        return SearchService(self.embeddings, self.lance).search(query, limit=limit)

    def ask(self, question: str, limit: int = 5) -> str:
        results = self.search(question, limit=limit)
        return self.answer_provider.answer(question, results)

    def status(self) -> StatusSummary:
        self.init()
        return self.sqlite.status(app_home=str(self.paths.home))
