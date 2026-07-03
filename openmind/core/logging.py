from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from openmind.core.config import AppPaths


def append_log(paths: AppPaths, event: str, message: str, **fields: Any) -> None:
    paths.ensure()
    payload = {
        "time": datetime.now(UTC).isoformat(),
        "event": event,
        "message": message,
        **fields,
    }
    log_path = paths.logs_path / "openmind.log"
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True, default=str) + "\n")
