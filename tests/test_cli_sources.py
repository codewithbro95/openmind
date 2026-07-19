from typer.testing import CliRunner

from openmind.cli.main import CUSTOM_FOLDER, _choose_source_paths, app
from openmind.core.models import FileRecord
from openmind.storage.sqlite_store import SQLiteStore


def test_source_add_reports_existing_indexed_source(monkeypatch, tmp_path):
    home = tmp_path / ".openmind"
    source_path = tmp_path / "docs"
    source_path.mkdir()
    monkeypatch.setenv("OPENMIND_HOME", str(home))

    runner = CliRunner()
    first = runner.invoke(app, ["source", "add", str(source_path)])
    assert first.exit_code == 0

    store = SQLiteStore(home / "openmind.sqlite")
    source = store.list_sources()[0]
    store.upsert_file(
        FileRecord(
            id="file_1",
            source_id=source.id,
            path=str(source_path / "notes.md"),
            name="notes.md",
            extension=".md",
            size=5,
            modified_at=1.0,
            content_hash="hash",
            status="indexed",
            indexed_at="2026-07-05T00:00:00+00:00",
        )
    )

    second = runner.invoke(app, ["source", "add", str(source_path)])

    assert second.exit_code == 0
    assert "Source already added" in second.output
    assert "already accessible" in second.output


def test_setup_source_selection_supports_multiple_folders(monkeypatch, tmp_path):
    docs = tmp_path / "docs"
    data = tmp_path / "data"
    docs.mkdir()
    data.mkdir()
    monkeypatch.setattr(
        "openmind.cli.main._checkbox_prompt",
        lambda message, choices: [str(docs), CUSTOM_FOLDER],
    )
    monkeypatch.setattr(
        "openmind.cli.main._text_prompt",
        lambda message, default="": str(data),
    )

    selected = _choose_source_paths([docs])

    assert selected == [docs, data]


def test_setup_custom_source_does_not_preselect_first_folder(monkeypatch, tmp_path):
    docs = tmp_path / "docs"
    custom = tmp_path / "custom"
    docs.mkdir()
    custom.mkdir()
    custom_prompted = []

    def choose_custom(message, choices):
        assert all(not choice.checked for choice in choices)
        return [CUSTOM_FOLDER]

    def enter_custom_path(message, default=""):
        custom_prompted.append(message)
        return str(custom)

    monkeypatch.setattr("openmind.cli.main._checkbox_prompt", choose_custom)
    monkeypatch.setattr("openmind.cli.main._text_prompt", enter_custom_path)

    selected = _choose_source_paths([docs])

    assert selected == [custom]
    assert custom_prompted == ["Custom folder path"]


def test_setup_source_selection_uses_checked_folders(monkeypatch, tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    monkeypatch.setattr(
        "openmind.cli.main._checkbox_prompt",
        lambda message, choices: [str(docs)],
    )

    selected = _choose_source_paths([docs])

    assert selected == [docs]
