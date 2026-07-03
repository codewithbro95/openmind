import json

from openmind.core.config import AppPaths
from openmind.core.logging import append_log


def test_append_log_writes_jsonl(tmp_path):
    paths = AppPaths(
        home=tmp_path,
        config_path=tmp_path / "config.toml",
        sqlite_path=tmp_path / "openmind.sqlite",
        lancedb_path=tmp_path / "lancedb",
        logs_path=tmp_path / "logs",
    )

    append_log(paths, "test.event", "hello", count=3)

    line = (tmp_path / "logs" / "openmind.log").read_text(encoding="utf-8").strip()
    payload = json.loads(line)
    assert payload["event"] == "test.event"
    assert payload["message"] == "hello"
    assert payload["count"] == 3
