from typer.testing import CliRunner

from openmind.cli.main import app
from openmind.llm.session import ChatSession


class FakeAskEngine:
    def __init__(self):
        self.calls: list[tuple[str, bool, str | None]] = []
        self.sessions: dict[str, ChatSession] = {}

    def ask_with_sources(self, question, limit=5, reasoning=False, session=None):
        self.calls.append((question, reasoning, session.id if session else None))
        return "Reasoned answer." if reasoning else "Direct answer.", []

    def create_chat_session(self):
        session = ChatSession()
        self.sessions[session.id] = session
        return session

    def end_chat_session(self, session_id):
        return self.sessions.pop(session_id, None) is not None


def test_cli_ask_disables_reasoning_by_default(monkeypatch):
    engine = FakeAskEngine()
    monkeypatch.setattr("openmind.cli.main.engine", lambda: engine)

    result = CliRunner().invoke(app, ["ask", "What is indexed?", "--no-stream"])

    assert result.exit_code == 0
    assert engine.calls == [("What is indexed?", False, None)]
    assert "Direct answer." in result.output


def test_cli_ask_enables_reasoning_when_requested(monkeypatch):
    engine = FakeAskEngine()
    monkeypatch.setattr("openmind.cli.main.engine", lambda: engine)

    result = CliRunner().invoke(
        app,
        ["ask", "What is indexed?", "--no-stream", "--reasoning"],
    )

    assert result.exit_code == 0
    assert engine.calls == [("What is indexed?", True, None)]
    assert "Reasoned answer." in result.output


def test_interactive_cli_uses_selected_reasoning_mode(monkeypatch):
    engine = FakeAskEngine()
    monkeypatch.setattr("openmind.cli.main.engine", lambda: engine)

    result = CliRunner().invoke(
        app,
        ["ask", "--no-stream", "--reasoning"],
        input="What is indexed?\n/exit\n",
    )

    assert result.exit_code == 0
    assert len(engine.calls) == 1
    assert engine.calls[0][0:2] == ("What is indexed?", True)
    assert engine.calls[0][2] is not None
    assert "Reasoned answer." in result.output
