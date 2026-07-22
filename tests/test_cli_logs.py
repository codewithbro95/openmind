import json
from types import SimpleNamespace

from typer.testing import CliRunner

from openmind.cli.main import app


def test_watch_log_mode_shows_structured_watch_events(monkeypatch, tmp_path):
    logs_path = tmp_path / "logs"
    logs_path.mkdir()
    records = [
        {
            "time": "2026-07-22T19:00:00+00:00",
            "event": "search.start",
            "message": "Searching local memory",
        },
        {
            "time": "2026-07-22T19:01:00+00:00",
            "event": "watch.event",
            "message": "Received supported file event",
            "path": "/tmp/notes.md",
        },
        {
            "time": "2026-07-22T19:02:00+00:00",
            "event": "watch.job.complete",
            "message": "File synchronization job completed",
            "path": "/tmp/notes.md",
        },
    ]
    (logs_path / "openmind.log").write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )
    (logs_path / "watch.log").write_text("worker diagnostic\n", encoding="utf-8")

    current = SimpleNamespace(
        paths=SimpleNamespace(logs_path=logs_path),
        init=lambda: None,
    )
    monkeypatch.setattr("openmind.cli.main.engine", lambda: current)

    result = CliRunner().invoke(
        app,
        ["dev", "logs", "--log", "watch", "--no-follow", "--lines", "20"],
    )

    assert result.exit_code == 0
    assert "watch.event" in result.output
    assert "watch.job.complete" in result.output
    assert "worker diagnostic" in result.output
    assert "search.start" not in result.output
