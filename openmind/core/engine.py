from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from openmind.core.config import AppPaths, OpenMindConfig
from openmind.core.errors import SourceRemovalBlockedError
from openmind.core.logging import append_log
from openmind.core.models import (
    Document,
    IndexJob,
    IndexSummary,
    ModelTransitionResult,
    SearchResult,
    Source,
    SourceRemovalResult,
    StatusSummary,
)
from openmind.embeddings.provider import EmbeddingProvider, SentenceTransformerEmbeddingProvider
from openmind.extractors import ExtractorRegistry, default_registry
from openmind.ingestion.chunker import TextChunker
from openmind.ingestion.normalizer import normalize_text
from openmind.llm.answer import AnswerProvider, ContextOnlyAnswerProvider
from openmind.llm.session import ChatSession
from openmind.providers.lmstudio import (
    LMStudioClient,
    LMStudioEmbeddingProvider,
    LMStudioImageDescriptionProvider,
    LMStudioLLMProvider,
)
from openmind.providers.lmstudio.models import LMStudioModel
from openmind.retrieval.search import SearchService
from openmind.sources.manager import SourceManager
from openmind.sources.scanner import SUPPORTED_EXTENSIONS, FileScanner
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
        self._config_lock = threading.RLock()
        self._chat_sessions_lock = threading.RLock()
        self._chat_sessions: dict[str, ChatSession] = {}
        self.config, self._config_fingerprint = self._read_config_snapshot()
        self.sqlite = sqlite_store or SQLiteStore(self.paths.sqlite_path)
        self.lance = lance_store or LanceStore(self.paths.lancedb_path)
        self.sources = SourceManager(self.sqlite)
        self.scanner = FileScanner()
        self.extractors = extractors or self._build_extractor_registry()
        self.chunker = TextChunker()
        self.embeddings = embeddings or self._build_embedding_provider()
        self.answer_provider = answer_provider or self._build_answer_provider()

    def init(self) -> AppPaths:
        self.paths.ensure()
        self.sqlite.initialize()
        self.lance.initialize()
        self._cleanup_orphaned_source_data()
        return self.paths

    def reload_config(self) -> OpenMindConfig:
        with self._config_lock:
            config, fingerprint = self._read_config_snapshot()
            self._apply_config(config, fingerprint)
        return self.config

    def reload_config_if_changed(self) -> bool:
        with self._config_lock:
            config, fingerprint = self._read_config_snapshot()
            if fingerprint == self._config_fingerprint:
                return False
            self._apply_config(config, fingerprint)
        self._log(
            "config.reload",
            "Reloaded configuration changed by another process",
            provider=config.provider.name,
            chat_model=config.models.chat_model,
            embedding_model=config.models.embedding_model,
            image_model=(config.extraction.images.model if config.extraction.images.enabled else None),
        )
        return True

    def _apply_config(self, config: OpenMindConfig, fingerprint: str | None) -> None:
        self.config = config
        self._config_fingerprint = fingerprint
        self.embeddings = self._build_embedding_provider()
        self.answer_provider = self._build_answer_provider()
        self.extractors = self._build_extractor_registry()

    def save_config(self, config: OpenMindConfig) -> None:
        self.paths.ensure()
        with self._config_lock:
            config.save(self.paths.config_path)
            fingerprint = self._fingerprint(config.to_toml())
            self._apply_config(config, fingerprint)

    def _read_config_snapshot(self) -> tuple[OpenMindConfig, str | None]:
        path = self.paths.config_path
        if not path.exists():
            return OpenMindConfig(), None
        text = path.read_text(encoding="utf-8")
        return OpenMindConfig.from_toml(text), self._fingerprint(text)

    @staticmethod
    def _fingerprint(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def add_source(self, path: str, recursive: bool = True) -> Source:
        self.init()
        return self.sources.add(path, recursive=recursive)

    def list_sources(self) -> list[Source]:
        self.init()
        return self.sources.list()

    def remove_source(self, source_id: str) -> SourceRemovalResult | None:
        self.init()
        active = self.sqlite.latest_unfinished_index_job()
        if active is not None and self._is_stale_pending_job(active):
            self.sqlite.update_index_job(
                active.id,
                status="failed",
                error="Index worker did not start.",
                completed_at=utc_now(),
            )
            active = None
        if active is not None:
            raise SourceRemovalBlockedError(
                f"Cannot remove a source while indexing job {active.id} is {active.status}. "
                "Stop indexing first with: openmind index stop"
            )

        source = self.sources.get(source_id)
        if source is None:
            return None
        if not self.sources.set_enabled(source_id, False):
            return None
        try:
            chunks_removed = self.lance.delete_source_chunks(source_id)
        except Exception:
            self.sources.set_enabled(source_id, True)
            raise
        files_removed = self.sources.remove(source_id)
        if files_removed is None:
            return None
        self._log(
            "source.remove",
            "Removed source and indexed memory",
            source_id=source_id,
            path=source.path,
            files_removed=files_removed,
            chunks_removed=chunks_removed,
        )
        return SourceRemovalResult(
            source_id=source.id,
            source_path=source.path,
            files_removed=files_removed,
            chunks_removed=chunks_removed,
        )

    def _cleanup_orphaned_source_data(self) -> None:
        for source_id in self.sqlite.orphaned_source_ids():
            chunks_removed = self.lance.delete_source_chunks(source_id)
            files_removed = self.sqlite.delete_files_for_source(source_id)
            self._log(
                "source.cleanup_orphan",
                "Removed indexed memory left by a deleted source",
                source_id=source_id,
                files_removed=files_removed,
                chunks_removed=chunks_removed,
            )

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
            records.extend(
                self.scanner.scan(
                    source,
                    include_content_hash=False,
                    supported_extensions=SUPPORTED_EXTENSIONS
                    & self.extractors.supported_extensions,
                )
            )
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
                    status=file_record.status,
                    error=file_record.error,
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
        reasoning: bool = False,
        history: list[dict[str, str]] | None = None,
        session: ChatSession | None = None,
    ) -> str:
        answer, _ = self.ask_with_sources(
            question,
            limit=limit,
            reasoning=reasoning,
            history=history,
            session=session,
        )
        return answer

    def ask_with_sources(
        self,
        question: str,
        limit: int = 5,
        reasoning: bool = False,
        history: list[dict[str, str]] | None = None,
        session: ChatSession | None = None,
    ) -> tuple[str, list[SearchResult]]:
        if session is not None:
            with session.lock:
                return self._answer_with_sources(
                    question,
                    limit=limit,
                    reasoning=reasoning,
                    history=session.history,
                    session=session,
                )
        return self._answer_with_sources(
            question,
            limit=limit,
            reasoning=reasoning,
            history=history,
            session=None,
        )

    def _answer_with_sources(
        self,
        question: str,
        *,
        limit: int,
        reasoning: bool,
        history: list[dict[str, str]] | None,
        session: ChatSession | None,
    ) -> tuple[str, list[SearchResult]]:
        self._log("ask.start", "Answering question", question=question, limit=limit)
        results = self.search(self._conversation_search_query(question, history), limit=limit)
        answer = self.answer_provider.answer(
            question,
            results,
            reasoning=reasoning,
            history=history,
            session=session,
        )
        if session is not None:
            session.record_turn(question, _visible_answer_for_history(answer))
        self._log("ask.finish", "Answer finished", question=question, sources=len(results))
        return answer, results

    def ask_stream(
        self,
        question: str,
        limit: int = 5,
        reasoning: bool = False,
        history: list[dict[str, str]] | None = None,
        session: ChatSession | None = None,
    ) -> Iterator[str]:
        stream, _ = self.ask_stream_with_sources(
            question,
            limit=limit,
            reasoning=reasoning,
            history=history,
            session=session,
        )
        yield from stream

    def ask_stream_with_sources(
        self,
        question: str,
        limit: int = 5,
        reasoning: bool = False,
        history: list[dict[str, str]] | None = None,
        session: ChatSession | None = None,
    ) -> tuple[Iterator[str], list[SearchResult]]:
        if session is not None:
            session.lock.acquire()
            history = session.history
        self._log("ask.start", "Streaming answer", question=question, limit=limit)
        try:
            results = self.search(self._conversation_search_query(question, history), limit=limit)
        except Exception:
            if session is not None:
                session.lock.release()
            raise

        def stream() -> Iterator[str]:
            chunks: list[str] = []
            try:
                for chunk in self.answer_provider.stream_answer(
                    question,
                    results,
                    reasoning=reasoning,
                    history=history,
                    session=session,
                ):
                    chunks.append(chunk)
                    yield chunk
                if session is not None:
                    session.record_turn(
                        question,
                        _visible_answer_for_history("".join(chunks).strip()),
                    )
                self._log(
                    "ask.finish",
                    "Streaming answer finished",
                    question=question,
                    sources=len(results),
                )
            finally:
                if session is not None:
                    session.lock.release()

        return stream(), results

    def create_chat_session(self) -> ChatSession:
        with self._chat_sessions_lock:
            self._prune_chat_sessions()
            if len(self._chat_sessions) >= 256:
                oldest = min(
                    self._chat_sessions.values(),
                    key=lambda existing: existing.updated_at,
                )
                oldest.reset()
                self._chat_sessions.pop(oldest.id, None)
            session = ChatSession()
            self._chat_sessions[session.id] = session
            return session

    def chat_session(self, session_id: str) -> ChatSession | None:
        with self._chat_sessions_lock:
            self._prune_chat_sessions()
            return self._chat_sessions.get(session_id)

    def end_chat_session(self, session_id: str) -> bool:
        with self._chat_sessions_lock:
            session = self._chat_sessions.pop(session_id, None)
            if session is None:
                return False
            session.reset()
            return True

    def _prune_chat_sessions(self, max_age_seconds: float = 4 * 60 * 60) -> None:
        cutoff = time.monotonic() - max_age_seconds
        expired = [
            session_id
            for session_id, session in self._chat_sessions.items()
            if session.updated_at < cutoff
        ]
        for session_id in expired:
            session = self._chat_sessions.pop(session_id, None)
            if session is not None:
                session.reset()

    def status(self) -> StatusSummary:
        self.init()
        return self.sqlite.status(app_home=str(self.paths.home))

    def lmstudio_client(self, config: OpenMindConfig | None = None) -> LMStudioClient:
        selected_config = config or self.config
        return LMStudioClient(
            base_url=selected_config.provider.base_url,
            api_token=os.environ.get(selected_config.provider.api_token_env),
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
        for model_key in self._selected_model_keys(self.config):
            loaded.append(client.load_model_if_needed(model_key))
        return loaded

    def update_model_config(
        self,
        config: OpenMindConfig,
        *,
        load: bool = True,
    ) -> ModelTransitionResult:
        previous = self.config.model_copy(deep=True)
        if not load:
            self.save_config(config)
            return ModelTransitionResult()

        previous_keys = set(self._selected_model_keys(previous))
        selected_keys = set(self._selected_model_keys(config))
        unload_results: list[dict] = []
        if previous.provider.name == "lmstudio":
            unload_results = self.lmstudio_client(previous).unload_models_if_loaded(
                previous_keys - selected_keys
            )

        self.save_config(config)
        load_results = self.load_configured_models()
        return ModelTransitionResult(
            unload_results=unload_results,
            load_results=load_results,
        )

    @staticmethod
    def _selected_model_keys(config: OpenMindConfig) -> list[str]:
        keys = [config.models.chat_model, config.models.embedding_model]
        if config.extraction.images.enabled:
            keys.append(config.extraction.images.model)
        return list(dict.fromkeys(key for key in keys if key))

    def _build_extractor_registry(self) -> ExtractorRegistry:
        return default_registry(
            self.config.extraction,
            image_description_provider=self._build_image_description_provider(),
        )

    def _build_image_description_provider(self):
        if (
            self.config.provider.name == "lmstudio"
            and self.config.extraction.images.enabled
            and self.config.extraction.images.model
        ):
            return LMStudioImageDescriptionProvider(
                client=self.lmstudio_client(),
                model=self.config.extraction.images.model,
            )
        return None

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
        if not self.sqlite.source_is_enabled(file_record.source_id):
            summary.files_skipped += 1
            return summary
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
                self.sqlite.upsert_file_if_source_enabled(file_record)
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
                file_record.error = extracted.metadata.get("ocr_error") or "No text extracted"
                self.sqlite.upsert_file_if_source_enabled(file_record)
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
            if not self.sqlite.upsert_file_if_source_enabled(file_record):
                self.lance.delete_file_chunks(file_record.id)
                summary.files_skipped += 1
                return summary
            summary.files_indexed += 1
            summary.chunks_created += len(chunks)
        except Exception as exc:
            file_record.status = "error"
            file_record.error = str(exc)
            self.sqlite.upsert_file_if_source_enabled(file_record)
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
        parts = [
            f"{item.get('role', 'message')}: {item.get('content', '')[-700:]}"
            for item in recent
        ]
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


def _visible_answer_for_history(answer: str) -> str:
    if answer.startswith("## Thinking") and "## Answer" in answer:
        return answer.split("## Answer", 1)[1].strip()
    return answer
