from openmind.core.models import Source
from openmind.sources.scanner import FileScanner


def test_scanner_finds_supported_files_and_ignores_noisy_dirs(tmp_path):
    (tmp_path / "notes.md").write_text("Holiday plan", encoding="utf-8")
    (tmp_path / "script.py").write_text("print('project code')", encoding="utf-8")
    (tmp_path / "config.json").write_text("{}", encoding="utf-8")
    (tmp_path / "image.png").write_text("image bytes placeholder", encoding="utf-8")
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

    assert [record.name for record in records] == ["notes.md", "image.png"]
    assert records[0].extension == ".md"
    assert records[0].content_hash


def test_scanner_skips_project_internals_but_keeps_high_level_docs(tmp_path):
    project = tmp_path / "playground.swiftpm"
    asset_dir = project / "Assets.xcassets" / "AccentColor.colorset"
    asset_dir.mkdir(parents=True)
    (asset_dir / "Contents.json").write_text("{}", encoding="utf-8")
    (project / "Package.swift").write_text("// package", encoding="utf-8")
    (project / "README.md").write_text("Project overview", encoding="utf-8")
    (project / "docs.html").write_text("<h1>Docs</h1>", encoding="utf-8")
    source = Source(
        id="src_1",
        path=str(tmp_path),
        recursive=True,
        enabled=True,
        created_at="2026-01-01T00:00:00+00:00",
    )

    records = FileScanner().scan(source)

    assert sorted(record.name for record in records) == ["README.md", "docs.html"]


def test_scanner_can_scan_metadata_without_hashing_content(tmp_path):
    (tmp_path / "notes.md").write_text("Holiday plan", encoding="utf-8")
    source = Source(
        id="src_1",
        path=str(tmp_path),
        recursive=True,
        enabled=True,
        created_at="2026-01-01T00:00:00+00:00",
    )

    records = FileScanner().scan(source, include_content_hash=False)

    assert len(records) == 1
    assert records[0].content_hash == ""
    assert records[0].modified_at > 0


def test_scanner_can_be_limited_to_available_extractors(tmp_path):
    (tmp_path / "notes.md").write_text("Holiday plan", encoding="utf-8")
    (tmp_path / "image.png").write_text("image bytes placeholder", encoding="utf-8")
    source = Source(
        id="src_1",
        path=str(tmp_path),
        recursive=True,
        enabled=True,
        created_at="2026-01-01T00:00:00+00:00",
    )

    records = FileScanner().scan(source, supported_extensions={".md"})

    assert [record.name for record in records] == ["notes.md"]
