from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable

from watchdog.observers import Observer

from openmind.core.engine import OpenMindEngine
from openmind.core.models import Source
from openmind.sources.scanner import SUPPORTED_EXTENSIONS
from openmind.storage.sqlite_store import utc_now
from openmind.watcher.debounce import EventDebouncer
from openmind.watcher.errors import WatchAlreadyRunningError, WatchUnavailableError
from openmind.watcher.events import FileChangeEvent
from openmind.watcher.handler import WatchEventHandler
from openmind.watcher.state import WatchJob, WatchStatus


class WatchService:
    def __init__(
        self,
        engine: OpenMindEngine,
        *,
        debounce_seconds: float = 2.0,
        stability_interval: float = 1.0,
        stability_checks: int = 3,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.engine = engine
        self.debouncer = EventDebouncer(debounce_seconds)
        self.stability_interval = stability_interval
        self.stability_checks = stability_checks
        self.sleep = sleep
        self.supported_extensions = (
            SUPPORTED_EXTENSIONS & self.engine.extractors.supported_extensions
        )

    def run(self, stop_event: threading.Event | None = None) -> None:
        self.engine.init()
        sources, unavailable = self._available_sources()
        if not sources:
            raise WatchUnavailableError(
                "Watch mode needs at least one enabled source folder that is currently available."
            )
        self._claim(sources, unavailable)
        observer = Observer()
        try:
            self.engine.sqlite.recover_processing_watch_jobs()
            for source in sources:
                handler = WatchEventHandler(
                    source,
                    self.engine.scanner,
                    self.supported_extensions,
                    self.debouncer,
                    on_event=self._record_event,
                )
                observer.schedule(handler, source.path, recursive=source.recursive)
            # listen before catch-up so changes made during the scan are not missed.
            observer.start()
            catch_up = self._catch_up(sources)
            self.engine._log(
                "watch.start",
                "Watch mode started",
                sources=[source.path for source in sources],
                discovered_files=catch_up["discovered_files"],
                queued_jobs=catch_up["queued_jobs"],
                pid=os.getpid(),
            )
            self._work_loop(stop_event or threading.Event())
        except Exception as exc:
            self.engine.sqlite.update_watch_state(
                status="error",
                error=str(exc),
                current_file=None,
                stopped_at=utc_now(),
                pid=None,
            )
            self.engine._log("watch.error", "Watch mode failed", error=str(exc))
            raise
        finally:
            if observer.is_alive():
                observer.stop()
                observer.join(timeout=5)
            state = self.engine.sqlite.get_watch_state()
            if state is not None and state.status != "error":
                self.engine.sqlite.update_watch_state(
                    status="stopped",
                    stopped_at=utc_now(),
                    current_file=None,
                    pid=None,
                )
                self.engine._log("watch.stop", "Watch mode stopped")

    def start_background(self) -> WatchStatus:
        self.engine.init()
        current = self.status()
        if current.state in {"starting", "running", "stop_requested"}:
            return current
        sources, _ = self._available_sources()
        if not sources:
            raise WatchUnavailableError(
                "Watch mode needs at least one enabled source folder that is currently available."
            )
        # publish the starting state before spawning so the child cannot be overwritten.
        self.engine.sqlite.update_watch_state(
            status="starting",
            started_at=utc_now(),
            stopped_at=None,
            pid=None,
            error=None,
            sources_json=json.dumps([source.path for source in sources]),
        )
        log_path = self.engine.paths.logs_path / "watch.log"
        try:
            with log_path.open("a", encoding="utf-8") as log_file:
                process = subprocess.Popen(
                    [sys.executable, "-m", "openmind.cli.main", "watch", "worker"],
                    cwd=str(Path.cwd()),
                    env={**os.environ, "OPENMIND_HOME": str(self.engine.paths.home)},
                    stdin=subprocess.DEVNULL,
                    stdout=log_file,
                    stderr=log_file,
                    start_new_session=True,
                )
        except OSError as exc:
            self.engine.sqlite.update_watch_state(
                status="error",
                stopped_at=utc_now(),
                error=f"Could not start the watch process: {exc}",
            )
            self.engine._log("watch.spawn.failed", "Could not start watch worker", error=str(exc))
            raise WatchUnavailableError(f"Could not start the watch process: {exc}") from exc
        state = self.engine.sqlite.get_watch_state()
        if state is not None and state.status == "starting":
            self.engine.sqlite.update_watch_state(pid=process.pid)
        self.engine._log("watch.spawn", "Started watch worker process", pid=process.pid)
        for _ in range(20):
            self.sleep(0.05)
            status = self.status()
            if status.state != "starting":
                return status
        return self.status()

    def stop(self) -> WatchStatus:
        self._initialize_state_store()
        state = self.engine.sqlite.get_watch_state()
        if state is None or state.status in {"stopped", "error"}:
            return self.status()
        self.engine.sqlite.update_watch_state(status="stop_requested")
        self.engine._log("watch.stop_requested", "Watch mode stop requested", pid=state.pid)
        return self.status()

    def status(self) -> WatchStatus:
        self._initialize_state_store()
        state = self.engine.sqlite.get_watch_state()
        if state is None:
            return WatchStatus(state="stopped")
        if state.status in {"starting", "running", "stop_requested"} and state.pid:
            if not _pid_is_alive(state.pid):
                state = self.engine.sqlite.update_watch_state(
                    status="error",
                    error="Watch process stopped unexpectedly.",
                    stopped_at=utc_now(),
                    current_file=None,
                    pid=None,
                )
        errors = self.engine.sqlite.recent_watch_errors()
        if state.error:
            errors.insert(0, state.error)
        return WatchStatus(
            state=state.status,
            sources=state.sources,
            queued_jobs=self.engine.sqlite.queued_watch_job_count(),
            current_file=state.current_file,
            last_event_at=state.last_event_at,
            last_indexed_at=state.last_indexed_at,
            errors=errors[:5],
            pid=state.pid,
        )

    def _initialize_state_store(self) -> None:
        self.engine.paths.ensure()
        self.engine.sqlite.initialize()

    def queue_event(self, event: FileChangeEvent) -> WatchJob:
        job_type = {
            "created": "index_file",
            "modified": "reindex_file",
            "deleted": "delete_file",
        }[event.event_type]
        priority = 100 if job_type == "delete_file" else 50
        job = self.engine.sqlite.enqueue_watch_job(
            job_type,
            event.path,
            event.source_id,
            priority,
        )
        self.engine._log(
            "watch.job.queued",
            "Queued file synchronization job",
            job_id=job.id,
            job_type=job.job_type,
            path=job.path,
        )
        return job

    def process_next_job(self) -> WatchJob | None:
        job = self.engine.sqlite.claim_watch_job()
        if job is None:
            return None
        self.engine.sqlite.update_watch_state(current_file=job.path)
        self.engine._log(
            "watch.job.start",
            "Processing file synchronization job",
            job_id=job.id,
            job_type=job.job_type,
            path=job.path,
        )
        try:
            if job.job_type == "delete_file":
                self._delete_path(job.path)
            else:
                self._index_path(job)
            completed = self.engine.sqlite.finish_watch_job(job.id)
            self.engine.sqlite.update_watch_state(
                current_file=None,
                last_indexed_at=utc_now(),
            )
            self.engine._log(
                "watch.job.complete",
                "File synchronization job completed",
                job_id=job.id,
                job_type=job.job_type,
                path=job.path,
            )
            return completed
        except Exception as exc:
            failed = self.engine.sqlite.finish_watch_job(job.id, error=str(exc))
            self.engine.sqlite.update_watch_state(current_file=None)
            self.engine._log(
                "watch.job.failed",
                "File synchronization job failed",
                job_id=job.id,
                job_type=job.job_type,
                path=job.path,
                error=str(exc),
            )
            return failed

    def _claim(self, sources: list[Source], unavailable: list[str]) -> None:
        state = self.engine.sqlite.get_watch_state()
        if (
            state is not None
            and state.status in {"starting", "running", "stop_requested"}
            and state.pid
            and state.pid != os.getpid()
            and _pid_is_alive(state.pid)
        ):
            raise WatchAlreadyRunningError(f"Watch mode is already running with pid {state.pid}.")
        self.engine.sqlite.update_watch_state(
            status="running",
            started_at=utc_now(),
            stopped_at=None,
            pid=os.getpid(),
            error=("Unavailable sources: " + ", ".join(unavailable) if unavailable else None),
            current_file=None,
            sources_json=json.dumps([source.path for source in sources]),
        )

    def _available_sources(self) -> tuple[list[Source], list[str]]:
        available: list[Source] = []
        unavailable: list[str] = []
        for source in self.engine.sources.list(enabled_only=True):
            if Path(source.path).is_dir():
                available.append(source)
            else:
                unavailable.append(source.path)
                self.engine._log(
                    "watch.source.unavailable",
                    "Approved source is unavailable",
                    source_id=source.id,
                    path=source.path,
                )
        return available, unavailable

    def _catch_up(self, sources: list[Source]) -> dict[str, int]:
        # a full metadata scan closes gaps created while watch mode was stopped.
        discovered_files = 0
        queued_jobs = 0
        for source in sources:
            records = self.engine.scanner.scan(
                source,
                include_content_hash=False,
                supported_extensions=self.supported_extensions,
            )
            discovered_files += len(records)
            discovered = {record.path: record for record in records}
            for record in records:
                existing = self.engine.sqlite.file_by_path(record.path)
                if existing is None:
                    self.queue_event(FileChangeEvent("created", record.path, source.id))
                    queued_jobs += 1
                elif existing.size != record.size or existing.modified_at != record.modified_at:
                    self.queue_event(FileChangeEvent("modified", record.path, source.id))
                    queued_jobs += 1
            for existing in self.engine.sqlite.files_for_source(source.id):
                if existing.path not in discovered:
                    self.queue_event(FileChangeEvent("deleted", existing.path, source.id))
                    queued_jobs += 1
        self.engine._log(
            "watch.catch_up.complete",
            "Watch catch-up scan completed",
            discovered_files=discovered_files,
            queued_jobs=queued_jobs,
        )
        return {"discovered_files": discovered_files, "queued_jobs": queued_jobs}

    def _work_loop(self, stop_event: threading.Event) -> None:
        while not stop_event.is_set():
            state = self.engine.sqlite.get_watch_state()
            if state is not None and state.status == "stop_requested":
                break
            for event in self.debouncer.ready():
                self.queue_event(event)
            processed = self.process_next_job()
            if processed is None:
                stop_event.wait(0.2)

    def _record_event(self, event: FileChangeEvent) -> None:
        self.engine.sqlite.update_watch_state(last_event_at=event.received_at)
        self.engine._log(
            "watch.event",
            "Received supported file event",
            event_id=event.id,
            event_type=event.event_type,
            source_id=event.source_id,
            path=event.path,
        )

    def _index_path(self, job: WatchJob) -> None:
        source = self.engine.sources.get(job.source_id)
        if source is None or not source.enabled:
            raise RuntimeError("The source is no longer enabled.")
        path = Path(job.path)
        if not path.exists():
            self._delete_path(job.path)
            return
        if not self.engine.scanner.is_supported_path(
            path,
            source.path,
            self.supported_extensions,
            source_id=source.id,
        ):
            self._delete_path(job.path)
            return
        if not self._wait_until_stable(path):
            raise RuntimeError("The file did not become stable before indexing.")
        record = self.engine.scanner.record_for_path(
            source,
            path,
            include_content_hash=False,
            supported_extensions=self.supported_extensions,
        )
        if record is None:
            raise RuntimeError("The file is unavailable or unsupported.")
        summary = self.engine._index_file(record)
        if summary.errors:
            raise RuntimeError(record.error or "The file could not be indexed.")

    def _delete_path(self, path: str) -> None:
        record = self.engine.sqlite.file_by_path(path)
        if record is None:
            return
        self.engine.lance.delete_file_chunks(record.id)
        self.engine.sqlite.delete_file(record.id)

    def _wait_until_stable(self, path: Path) -> bool:
        # identical snapshots avoid reading a file while another process is writing it.
        previous: tuple[int, int] | None = None
        for _ in range(max(2, self.stability_checks)):
            try:
                stat = path.stat()
            except FileNotFoundError:
                return False
            current = (stat.st_size, stat.st_mtime_ns)
            if previous == current:
                return True
            previous = current
            self.sleep(self.stability_interval)
        return False


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
