from typer.testing import CliRunner

from openmind.cli.main import app
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
