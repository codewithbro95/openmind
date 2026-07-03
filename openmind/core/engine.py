from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime

from openmind.core.config import AppPaths, OpenMindConfig
from openmind.core.models import Document, IndexJob, IndexSummary, SearchResult, Source, StatusSummary
from openmind.embeddings.provider import EmbeddingProvider, SentenceTransformerEmbeddingProvider
from openmind.extractors import ExtractorRegistry, default_registry
from openmind.ingestion.chunker import TextChunker
from openmind.ingestion.normalizer import normalize_text
from openmind.llm.answer import AnswerProvider, ContextOnlyAnswerProvider
from openmind.providers.lmstudio import LMStudioClient, LMStudioEmbeddingProvider, LMStudioLLMProvider
from openmind.providers.lmstudio.models import LMStudioModel
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
        self.config = OpenMindConfig.load(self.paths.config_path)
        self.sqlite = sqlite_store or SQLiteStore(self.paths.sqlite_path)
        self.lance = lance_store or LanceStore(self.paths.lancedb_path)
        self.sources = SourceManager(self.sqlite)
        self.scanner = FileScanner()
        self.extractors = extractors or default_registry()
        self.chunker = TextChunker()
        self.embeddings = embeddings or self._build_embedding_provider()
        self.answer_provider = answer_provider or self._build_answer_provider()

    def init(self) -> AppPaths:
        self.paths.ensure()
        self.sqlite.initialize()
        self.lance.initialize()
        return self.paths

    def reload_config(self) -> OpenMindConfig:
        self.config = OpenMindConfig.load(self.paths.config_path)
        self.embeddings = self._build_embedding_provider()
        self.answer_provider = self._build_answer_provider()
        return self.config

    def save_config(self, config: OpenMindConfig) -> None:
        self.paths.ensure()
        config.save(self.paths.config_path)
        self.config = config
        self.embeddings = self._build_embedding_provider()
        self.answer_provider = self._build_answer_provider()

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
        records = self.discover_files()
        summary.files_seen = len(records)
        for file_record in records:
            file_summary = self._index_file(file_record)
            summary.files_indexed += file_summary.files_indexed
            summary.files_skipped += file_summary.files_skipped
            summary.errors += file_summary.errors
            summary.chunks_created += file_summary.chunks_created
        return summary

    def discover_files(self):
        records = []
        for source in self.sources.list(enabled_only=True):
            records.extend(self.scanner.scan(source))
        return records

    def create_index_job(self) -> IndexJob:
        self.init()
        return self.sqlite.create_index_job(f"job_{uuid.uuid4().hex[:12]}")

    def start_index_job(self) -> IndexJob:
        self.init()
        active = self.sqlite.latest_active_index_job()
        if active is not None:
            if not self._is_stale_pending_job(active):
                return active
            self.sqlite.update_index_job(
                active.id,
                status="failed",
                error="Index worker did not start. Start a new job with: openmind index start",
                completed_at=utc_now(),
            )
        job = self.create_index_job()
        env = os.environ.copy()
        env["OPENMIND_HOME"] = str(self.paths.home)
        log_path = self.paths.logs_path / f"index-{job.id}.log"
        log_file = log_path.open("a", encoding="utf-8")
        subprocess.Popen(
            [sys.executable, "-m", "openmind.cli.main", "index", "worker", "--job-id", job.id],
            cwd=str(PathLike.cwd()),
            env=env,
            stdout=log_file,
            stderr=log_file,
            start_new_session=True,
        )
        return job

    def run_index_worker(self, job_id: str) -> IndexJob:
        self.init()
        job = self.sqlite.get_index_job(job_id)
        if job is None:
            raise KeyError(f"Unknown index job: {job_id}")

        try:
            self.sqlite.update_index_job(
                job_id,
                status="discovering",
                total_files=0,
                processed_files=0,
                indexed_files=0,
                skipped_files=0,
                failed_files=0,
                total_chunks=0,
                current_file=None,
                error=None,
                completed_at=None,
            )
            records = self.discover_files()
            self.sqlite.update_index_job(job_id, total_files=len(records), status="running")

            for file_record in records:
                job = self.sqlite.get_index_job(job_id)
                if job and job.status == "stop_requested":
                    return self.sqlite.update_index_job(
                        job_id,
                        status="stopped",
                        completed_at=utc_now(),
                        current_file=None,
                    )

                while job and job.status in {"pause_requested", "paused"}:
                    self.sqlite.update_index_job(job_id, status="paused")
                    time.sleep(1)
                    job = self.sqlite.get_index_job(job_id)
                    if job and job.status == "stop_requested":
                        return self.sqlite.update_index_job(
                            job_id,
                            status="stopped",
                            completed_at=utc_now(),
                            current_file=None,
                        )

                self.sqlite.update_index_job(job_id, status="running", current_file=file_record.path)
                summary = self._index_file(file_record)
                current = self.sqlite.get_index_job(job_id)
                processed = (current.processed_files if current else 0) + 1
                self.sqlite.update_index_job(
                    job_id,
                    processed_files=processed,
                    indexed_files=(current.indexed_files if current else 0) + summary.files_indexed,
                    skipped_files=(current.skipped_files if current else 0) + summary.files_skipped,
                    failed_files=(current.failed_files if current else 0) + summary.errors,
                    total_chunks=(current.total_chunks if current else 0) + summary.chunks_created,
                )

            return self.sqlite.update_index_job(
                job_id,
                status="completed",
                completed_at=utc_now(),
                current_file=None,
            )
        except Exception as exc:
            return self.sqlite.update_index_job(
                job_id,
                status="failed",
                error=str(exc),
                completed_at=utc_now(),
                current_file=None,
            )

    def index_job_status(self) -> IndexJob | None:
        self.init()
        return self.sqlite.latest_index_job()

    def pause_index_job(self) -> IndexJob | None:
        job = self.index_job_status()
        if job and job.status in {"pending", "discovering", "running"}:
            return self.sqlite.update_index_job(job.id, status="pause_requested")
        return job

    def resume_index_job(self) -> IndexJob | None:
        job = self.index_job_status()
        if job and job.status in {"pause_requested", "paused"}:
            return self.sqlite.update_index_job(job.id, status="running")
        return job

    def stop_index_job(self) -> IndexJob | None:
        job = self.index_job_status()
        if job and job.status not in {"completed", "failed", "stopped"}:
            if job.status == "pending":
                return self.sqlite.update_index_job(
                    job.id,
                    status="stopped",
                    completed_at=utc_now(),
                    current_file=None,
                    error="Stopped before worker started.",
                )
            return self.sqlite.update_index_job(job.id, status="stop_requested")
        return job

    def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        self.init()
        return SearchService(self.embeddings, self.lance).search(query, limit=limit)

    def ask(self, question: str, limit: int = 5) -> str:
        results = self.search(question, limit=limit)
        return self.answer_provider.answer(question, results)

    def status(self) -> StatusSummary:
        self.init()
        return self.sqlite.status(app_home=str(self.paths.home))

    def lmstudio_client(self) -> LMStudioClient:
        return LMStudioClient(
            base_url=self.config.provider.base_url,
            api_token=os.environ.get(self.config.provider.api_token_env),
        )

    def provider_status(self) -> tuple[bool, str]:
        if self.config.provider.name != "lmstudio":
            return False, f"Configured provider is {self.config.provider.name!r}, not LM Studio."
        client = self.lmstudio_client()
        if client.health_check():
            return True, f"LM Studio is reachable at {self.config.provider.base_url}."
        return (
            False,
            f"LM Studio is not reachable at {self.config.provider.base_url}. "
            "Start it from the LM Studio Developer tab or run: lms server start",
        )

    def list_lmstudio_models(self) -> list[LMStudioModel]:
        return self.lmstudio_client().list_models()

    def load_configured_models(self) -> list[dict]:
        loaded = []
        client = self.lmstudio_client()
        if self.config.models.chat_model:
            loaded.append(client.load_model(self.config.models.chat_model))
        if self.config.models.embedding_model:
            loaded.append(client.load_model(self.config.models.embedding_model))
        return loaded

    def _build_embedding_provider(self) -> EmbeddingProvider:
        if self.config.provider.name == "lmstudio" and self.config.models.embedding_model:
            return LMStudioEmbeddingProvider(
                client=self.lmstudio_client(),
                model=self.config.models.embedding_model,
            )
        return SentenceTransformerEmbeddingProvider()

    def _build_answer_provider(self) -> AnswerProvider:
        if self.config.provider.name == "lmstudio" and self.config.models.chat_model:
            return LMStudioLLMProvider(
                client=self.lmstudio_client(),
                model=self.config.models.chat_model,
            )
        return ContextOnlyAnswerProvider()

    def _index_file(self, file_record) -> IndexSummary:
        summary = IndexSummary()
        existing = self.sqlite.file_by_path(file_record.path)
        if existing and existing.content_hash == file_record.content_hash and existing.status == "indexed":
            summary.files_skipped += 1
            return summary

        try:
            extractor = self.extractors.for_path(file_record.path)
            extracted = extractor.extract(file_record.path)
            text = normalize_text(extracted.text)
            if not text:
                file_record.status = "skipped"
                file_record.error = "No text extracted"
                self.sqlite.upsert_file(file_record)
                summary.files_skipped += 1
                return summary

            document = Document(
                id=f"doc_{uuid.uuid4().hex}",
                source_id=file_record.source_id,
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
            file_record.error = None
            self.sqlite.upsert_file(file_record)
            summary.files_indexed += 1
            summary.chunks_created += len(chunks)
        except Exception as exc:
            file_record.status = "error"
            file_record.error = str(exc)
            self.sqlite.upsert_file(file_record)
            summary.errors += 1
        return summary

    def _is_stale_pending_job(self, job: IndexJob) -> bool:
        if job.status != "pending" or not job.updated_at:
            return False
        try:
            updated_at = datetime.fromisoformat(job.updated_at)
        except ValueError:
            return False
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=UTC)
        return (datetime.now(UTC) - updated_at).total_seconds() > 30


class PathLike:
    @staticmethod
    def cwd() -> str:
        from pathlib import Path

        return str(Path(__file__).resolve().parents[2])
