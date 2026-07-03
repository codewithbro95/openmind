from openmind.core.models import Source
from openmind.sources.scanner import FileScanner


def test_scanner_finds_supported_files_and_ignores_noisy_dirs(tmp_path):
    (tmp_path / "notes.md").write_text("holiday plan", encoding="utf-8")
    (tmp_path / "image.png").write_text("not supported", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "package.json").write_text("{}", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("ignored", encoding="utf-8")

    source = Source(
        id="src_1",
        path=str(tmp_path),
        recursive=True,
        enabled=True,
        created_at="2026-01-01T00:00:00+00:00",
    )

    records = FileScanner().scan(source)

    assert [record.name for record in records] == ["notes.md"]
    assert records[0].extension == ".md"
    assert records[0].content_hash
