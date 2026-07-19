from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field


@dataclass
class ChatSession:
    id: str = field(default_factory=lambda: f"chat_{uuid.uuid4().hex[:16]}")
    provider_state: dict[str, str] = field(default_factory=dict)
    history: list[dict[str, str]] = field(default_factory=list)
    updated_at: float = field(default_factory=time.monotonic)
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def record_turn(self, question: str, answer: str, max_messages: int = 12) -> None:
        self.history.extend(
            [
                {"role": "user", "content": question},
                {"role": "assistant", "content": answer},
            ]
        )
        self.history = self.history[-max_messages:]
        self.updated_at = time.monotonic()

    def reset(self) -> None:
        self.provider_state.clear()
        self.history.clear()
        self.updated_at = time.monotonic()
