from __future__ import annotations

from pathlib import Path
from typing import Callable

from watchdog.events import FileSystemEvent, FileSystemEventHandler, FileSystemMovedEvent

from openmind.core.models import Source
from openmind.sources.scanner import FileScanner
from openmind.watcher.debounce import EventDebouncer
from openmind.watcher.events import FileChangeEvent, WatchEventType


class WatchEventHandler(FileSystemEventHandler):
    def __init__(
        self,
        source: Source,
        scanner: FileScanner,
        supported_extensions: set[str],
        debouncer: EventDebouncer,
        on_event: Callable[[FileChangeEvent], None] | None = None,
    ):
        self.source = source
        self.root = Path(source.path)
        self.scanner = scanner
        self.supported_extensions = supported_extensions
        self.debouncer = debouncer
        self.on_event = on_event

    def on_created(self, event: FileSystemEvent) -> None:
        self._accept("created", event.src_path, event.is_directory)

    def on_modified(self, event: FileSystemEvent) -> None:
        self._accept("modified", event.src_path, event.is_directory)

    def on_deleted(self, event: FileSystemEvent) -> None:
        self._accept("deleted", event.src_path, event.is_directory)

    def on_moved(self, event: FileSystemMovedEvent) -> None:
        if event.is_directory:
            return
        # moves remove the old memory before indexing the destination.
        self._accept("deleted", event.src_path, False)
        self._accept("created", event.dest_path, False)

    def _accept(self, event_type: WatchEventType, path: str, is_directory: bool) -> None:
        if is_directory:
            return
        normalized = str(Path(path).expanduser().resolve(strict=False))
        if not self.scanner.is_supported_path(
            normalized,
            self.root,
            self.supported_extensions,
            source_id=self.source.id,
        ):
            return
        event = FileChangeEvent(
            event_type=event_type,
            path=normalized,
            source_id=self.source.id,
        )
        self.debouncer.push(event)
        if self.on_event is not None:
            self.on_event(event)
