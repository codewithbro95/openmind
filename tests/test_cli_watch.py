from typer.testing import CliRunner

from openmind.cli.main import app
from openmind.watcher.state import WatchStatus


def test_bare_watch_command_starts_shared_background_worker(monkeypatch):
    calls = []

    class FakeEngine:
        def start_watch(self):
            calls.append("start")
            return WatchStatus(state="running", pid=4321)

    monkeypatch.setattr("openmind.cli.main.engine", lambda: FakeEngine())

    result = CliRunner().invoke(app, ["watch"])

    assert result.exit_code == 0
    assert calls == ["start"]
    assert "running in the background" in result.output
    assert "openmind watch stop" in result.output


def test_watch_status_and_stop_use_shared_engine_state(monkeypatch):
    current = WatchStatus(
        state="running",
        sources=["/tmp/documents"],
        queued_jobs=2,
        current_file="/tmp/documents/notes.md",
        pid=4321,
    )

    class FakeEngine:
        def watch_status(self):
            return current

        def stop_watch(self):
            return current.model_copy(update={"state": "stop_requested"})

    monkeypatch.setattr("openmind.cli.main.engine", lambda: FakeEngine())

    status = CliRunner().invoke(app, ["watch", "status"])
    stopped = CliRunner().invoke(app, ["watch", "stop"])

    assert status.exit_code == 0
    assert "running" in status.output
    assert "notes.md" in status.output
    assert stopped.exit_code == 0
    assert "stop requested" in stopped.output.lower()
