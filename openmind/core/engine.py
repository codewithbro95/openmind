from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from openmind.core.config import AppPaths, OpenMindConfig
from openmind.core.logging import append_log
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
            summary.files_already_indexed += file_summary.files_already_indexed
            summary.errors += file_summary.errors
            summary.chunks_created += file_summary.chunks_created
        return summary

    def discover_files(self):
        records = []
        for source in self.sources.list(enabled_only=True):
            records.extend(self.scanner.scan(source, include_content_hash=False))
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
        self._log("index.start", "Starting background index worker", job_id=job.id)
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
            self._log("index.worker.start", "Index worker started", job_id=job_id)
            self.sqlite.update_index_job(
                job_id,
                status="discovering",
                total_files=0,
                processed_files=0,
                indexed_files=0,
                skipped_files=0,
                already_indexed_files=0,
                failed_files=0,
                total_chunks=0,
                current_file=None,
                error=None,
                completed_at=None,
            )
            records = self.discover_files()
            self._log(
                "index.discovery.complete",
                "File discovery complete",
                job_id=job_id,
                total_files=len(records),
            )
            self.sqlite.update_index_job(job_id, total_files=len(records), status="running")

            for file_record in records:
                job = self.sqlite.get_index_job(job_id)
                if job and job.status == "stop_requested":
                    self._log("index.worker.stopped", "Index worker stopped", job_id=job_id)
                    return self.sqlite.update_index_job(
                        job_id,
                        status="stopped",
                        completed_at=utc_now(),
                        current_file=None,
                    )

                while job and job.status in {"pause_requested", "paused"}:
                    self._log("index.worker.paused", "Index worker paused", job_id=job_id)
                    self.sqlite.update_index_job(job_id, status="paused")
                    time.sleep(1)
                    job = self.sqlite.get_index_job(job_id)
                    if job and job.status == "stop_requested":
                        self._log("index.worker.stopped", "Index worker stopped", job_id=job_id)
                        return self.sqlite.update_index_job(
                            job_id,
                            status="stopped",
                            completed_at=utc_now(),
                            current_file=None,
                        )

                self.sqlite.update_index_job(job_id, status="running", current_file=file_record.path)
                self._log(
                    "index.file.check",
                    "Checking file",
                    job_id=job_id,
                    path=file_record.path,
                    extension=file_record.extension,
                )
                summary = self._index_file(file_record)
                self._log(
                    "index.file.finish",
                    "Finished file",
                    job_id=job_id,
                    path=file_record.path,
                    indexed=summary.files_indexed,
                    skipped=summary.files_skipped,
                    already_indexed=summary.files_already_indexed,
                    failed=summary.errors,
                    chunks=summary.chunks_created,
                )
                current = self.sqlite.get_index_job(job_id)
                processed = (current.processed_files if current else 0) + 1
                self.sqlite.update_index_job(
                    job_id,
                    processed_files=processed,
                    indexed_files=(current.indexed_files if current else 0) + summary.files_indexed,
                    skipped_files=(current.skipped_files if current else 0) + summary.files_skipped,
                    already_indexed_files=(current.already_indexed_files if current else 0)
                    + summary.files_already_indexed,
                    failed_files=(current.failed_files if current else 0) + summary.errors,
                    total_chunks=(current.total_chunks if current else 0) + summary.chunks_created,
                )

            self._log("index.worker.complete", "Index worker completed", job_id=job_id)
            return self.sqlite.update_index_job(
                job_id,
                status="completed",
                completed_at=utc_now(),
                current_file=None,
            )
        except Exception as exc:
            self._log("index.worker.failed", "Index worker failed", job_id=job_id, error=str(exc))
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
        self._log("search.start", "Searching local memory", query=query, limit=limit)
        results = SearchService(self.embeddings, self.lance).search(query, limit=limit)
        self._log("search.finish", "Search finished", query=query, results=len(results))
        return results

    def ask(
        self,
        question: str,
        limit: int = 5,
        show_thinking: bool = False,
        history: list[dict[str, str]] | None = None,
    ) -> str:
        self._log("ask.start", "Answering question", question=question, limit=limit)
        results = self.search(self._conversation_search_query(question, history), limit=limit)
        answer = self.answer_provider.answer(
            question,
            results,
            show_thinking=show_thinking,
            history=history,
        )
        self._log("ask.finish", "Answer finished", question=question, sources=len(results))
        return answer

    def ask_stream(
        self,
        question: str,
        limit: int = 5,
        show_thinking: bool = False,
        history: list[dict[str, str]] | None = None,
    ) -> Iterator[str]:
        self._log("ask.start", "Streaming answer", question=question, limit=limit)
        results = self.search(self._conversation_search_query(question, history), limit=limit)
        if results:
            yield _retrieval_preamble(results)
        for chunk in self.answer_provider.stream_answer(
            question,
            results,
            show_thinking=show_thinking,
            history=history,
        ):
            yield chunk
        self._log("ask.finish", "Streaming answer finished", question=question, sources=len(results))

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
            loaded.append(client.load_model_if_needed(self.config.models.chat_model))
        if self.config.models.embedding_model:
            loaded.append(client.load_model_if_needed(self.config.models.embedding_model))
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
        if existing and existing.status == "indexed":
            if _same_file_metadata(existing, file_record):
                summary.files_skipped += 1
                summary.files_already_indexed += 1
                return summary

            if not file_record.content_hash:
                file_record.content_hash = self.scanner.content_hash(Path(file_record.path))
            if existing.content_hash == file_record.content_hash:
                file_record.status = "indexed"
                file_record.indexed_at = existing.indexed_at
                file_record.error = None
                self.sqlite.upsert_file(file_record)
                summary.files_skipped += 1
                summary.files_already_indexed += 1
                return summary
        elif not file_record.content_hash:
            file_record.content_hash = self.scanner.content_hash(Path(file_record.path))

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

    def _log(self, event: str, message: str, **fields) -> None:
        append_log(self.paths, event, message, **fields)

    def _conversation_search_query(
        self,
        question: str,
        history: list[dict[str, str]] | None,
    ) -> str:
        if not history:
            return question
        recent = history[-6:]
        parts = [f"{item.get('role', 'message')}: {item.get('content', '')}" for item in recent]
        parts.append(f"user: {question}")
        return "\n".join(parts)


class PathLike:
    @staticmethod
    def cwd() -> str:
        from pathlib import Path

        return str(Path(__file__).resolve().parents[2])


def _same_file_metadata(existing, candidate) -> bool:
    return (
        existing.size == candidate.size
        and abs(existing.modified_at - candidate.modified_at) < 0.000001
    )


def _retrieval_preamble(results: list[SearchResult]) -> str:
    sources: list[str] = []
    seen: set[str] = set()
    for result in results:
        if result.path in seen:
            continue
        seen.add(result.path)
        sources.append(result.path)
        if len(sources) == 3:
            break
    lines = [f"Found {len(results)} relevant chunk(s) in local memory."]
    if sources:
        lines.append("Top source(s):")
        lines.extend(f"- {source}" for source in sources)
    lines.append("")
    lines.append("Generating answer:")
    lines.append("")
    return "\n".join(lines)
