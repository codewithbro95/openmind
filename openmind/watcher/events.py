from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Literal

from openmind.storage.sqlite_store import utc_now

WatchEventType = Literal["created", "modified", "deleted"]


@dataclass(frozen=True)
class FileChangeEvent:
    event_type: WatchEventType
    path: str
    source_id: str
    received_at: str = field(default_factory=utc_now)
    id: str = field(default_factory=lambda: f"event_{uuid.uuid4().hex[:16]}")
