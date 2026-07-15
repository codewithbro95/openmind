from typer.testing import CliRunner

import pytest
import typer

from openmind.cli.main import _resolve_source_selection, app
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


def test_setup_source_selection_accepts_pasted_folder_path(tmp_path):
    docs = tmp_path / "docs"
    data = tmp_path / "data"
    docs.mkdir()
    data.mkdir()

    selected = _resolve_source_selection(f"1,{data}", [docs])

    assert selected == [docs, data]


def test_setup_source_selection_rejects_unknown_text(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()

    with pytest.raises(typer.BadParameter) as exc:
        _resolve_source_selection("not-a-folder", [docs])

    assert "Enter a listed number or an existing folder path" in str(exc.value)
