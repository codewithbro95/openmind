from __future__ import annotations

from fastapi.testclient import TestClient
from typer.testing import CliRunner
from watchdog.events import FileCreatedEvent

from openmind.api.app import create_app
from openmind.cli.main import app
from openmind.core.config import AppPaths
from openmind.core.engine import OpenMindEngine
from openmind.embeddings.provider import HashEmbeddingProvider
from openmind.ignore.errors import ProtectedIgnoreRuleError
from openmind.ignore.models import IgnoreDecision
from openmind.watcher.debounce import EventDebouncer
from openmind.watcher.handler import WatchEventHandler

TOKEN = "ignore-test-token-abcdefghijklmnopqrstuvwxyz"


def test_init_seeds_visible_protected_system_rules(tmp_path):
    engine = _engine(tmp_path)

    rules = engine.list_ignore_rules()

    assert any(rule.type == "folder_name" and rule.value == "node_modules" for rule in rules)
    assert any(rule.type == "pattern" and rule.value == "*.pem" for rule in rules)
    assert all(rule.is_system and rule.enabled for rule in rules)

    protected = next(rule for rule in rules if rule.value == "*.pem")
    try:
        engine.update_ignore_rule(protected.id, enabled=False)
    except ProtectedIgnoreRuleError:
        pass
    else:
        raise AssertionError("system ignore rules must not be disabled")


def test_rule_matching_supports_patterns_extensions_names_types_sizes_and_paths(tmp_path):
    engine = _engine(tmp_path)
    source_path = tmp_path / "documents"
    source_path.mkdir()
    source = engine.add_source(str(source_path))
    private_path = source_path / "private"

    cases = [
        ("pattern", "report-*.pdf", source_path / "report-2026.pdf", None),
        ("extension", "jpg", source_path / "photo.jpg", None),
        ("folder_name", "archive", source_path / "archive" / "notes.md", None),
        ("file_name", "receipt.txt", source_path / "receipt.txt", None),
        ("source_type", "image", source_path / "diagram.png", None),
        ("max_file_size", "1KB", source_path / "large.pdf", 2048),
        ("path", str(private_path), private_path / "taxes.pdf", None),
    ]

    for rule_type, value, candidate, size in cases:
        rule = engine.add_ignore_rule(rule_type, value)
        decision = engine.test_ignore_path(str(candidate), source_id=source.id, size=size)
        assert decision.ignored
        assert decision.rule_id == rule.id

    hidden = engine.test_ignore_path(str(source_path / ".private" / "notes.md"), source_id=source.id)
    assert hidden.ignored
    assert hidden.rule_type == "hidden_files"


def test_source_rule_applies_only_to_its_selected_source(tmp_path):
    engine = _engine(tmp_path)
    first_path = tmp_path / "first"
    second_path = tmp_path / "second"
    first_path.mkdir()
    second_path.mkdir()
    first = engine.add_source(str(first_path))
    second = engine.add_source(str(second_path))
    rule = engine.add_ignore_rule(
        "extension",
        ".pdf",
        scope="source",
        source_id=first.id,
    )

    first_decision = engine.test_ignore_path(str(first_path / "notes.pdf"), source_id=first.id)
    second_decision = engine.test_ignore_path(str(second_path / "notes.pdf"), source_id=second.id)

    assert first_decision.rule_id == rule.id
    assert not second_decision.ignored


def test_scanner_and_watcher_share_user_ignore_rules(tmp_path):
    engine = _engine(tmp_path)
    source_path = tmp_path / "documents"
    source_path.mkdir()
    source = engine.add_source(str(source_path))
    ignored = source_path / "private-notes.md"
    allowed = source_path / "public-notes.md"
    ignored.write_text("private", encoding="utf-8")
    allowed.write_text("public", encoding="utf-8")
    engine.add_ignore_rule("pattern", "private-*")

    records = engine.scanner.scan(source)
    debouncer = EventDebouncer(delay_seconds=0)
    handler = WatchEventHandler(
        source,
        engine.scanner,
        {".md"},
        debouncer,
    )
    handler.on_created(FileCreatedEvent(str(ignored)))

    assert [record.name for record in records] == ["public-notes.md"]
    assert debouncer.ready() == []


def test_enabling_rule_removes_existing_memory_without_deleting_file(tmp_path):
    engine = _engine(tmp_path)
    source_path = tmp_path / "documents"
    source_path.mkdir()
    file_path = source_path / "notes.txt"
    file_path.write_text("searchable private notes", encoding="utf-8")
    engine.add_source(str(source_path))
    engine.index()
    record = engine.sqlite.file_by_path(str(file_path))
    assert engine.lance.count_chunks() == 1

    rule = engine.add_ignore_rule("extension", ".txt")

    updated = engine.sqlite.file_by_path(str(file_path))
    assert updated.status == "skipped"
    assert updated.indexed_at is None
    assert engine.lance.chunks_for_file(record.id) == []
    assert file_path.exists()

    engine.update_ignore_rule(rule.id, enabled=False)
    engine.index()
    assert engine.lance.count_chunks() == 1


def test_indexing_rechecks_rules_before_writing_chunks(monkeypatch, tmp_path):
    engine = _engine(tmp_path)
    source_path = tmp_path / "documents"
    source_path.mkdir()
    file_path = source_path / "notes.txt"
    file_path.write_text("content discovered before rule change", encoding="utf-8")
    source = engine.add_source(str(source_path))
    record = engine.scanner.record_for_path(source, file_path)
    decisions = iter(
        [
            IgnoreDecision.allowed(),
            IgnoreDecision(
                ignored=True,
                rule_id="ign_concurrent",
                rule_type="extension",
                rule_value=".txt",
                reason="Concurrent rule",
            ),
        ]
    )
    monkeypatch.setattr(engine.ignore, "should_ignore", lambda *args, **kwargs: next(decisions))

    summary = engine._index_file(record)

    assert summary.files_skipped == 1
    assert engine.lance.count_chunks() == 0
    assert engine.sqlite.file_by_path(str(file_path)).status == "skipped"


def test_cli_can_add_list_test_disable_and_remove_user_rule(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENMIND_HOME", str(tmp_path / "openmind"))
    runner = CliRunner()

    added = runner.invoke(
        app,
        ["ignore", "add", "extension", ".mp4", "--reason", "Video files"],
    )
    listed = runner.invoke(app, ["ignore", "list"])
    tested = runner.invoke(app, ["ignore", "test", str(tmp_path / "video.mp4")])

    assert added.exit_code == 0
    rule_id = added.output.split("Added ignore rule ", 1)[1].split(":", 1)[0]
    assert rule_id.startswith("ign_")
    assert listed.exit_code == 0 and ".mp4" in listed.output
    assert tested.exit_code == 0 and rule_id in tested.output

    disabled = runner.invoke(app, ["ignore", "disable", rule_id])
    removed = runner.invoke(app, ["ignore", "remove", rule_id])

    assert disabled.exit_code == 0
    assert removed.exit_code == 0


def test_api_manages_and_explains_ignore_rules(tmp_path):
    engine = _engine(tmp_path)
    api = create_app(engine=engine, api_token=TOKEN)
    headers = {"Authorization": f"Bearer {TOKEN}"}

    with TestClient(api) as client:
        created = client.post(
            "/api/v1/ignore-rules",
            headers=headers,
            json={
                "type": "extension",
                "value": ".mp4",
                "reason": "Video files",
            },
        )
        listed = client.get("/api/v1/ignore-rules", headers=headers)
        tested = client.post(
            "/api/v1/ignore-rules/test",
            headers=headers,
            json={"path": str(tmp_path / "movie.mp4")},
        )
        disabled = client.patch(
            f"/api/v1/ignore-rules/{created.json()['id']}",
            headers=headers,
            json={"enabled": False},
        )
        deleted = client.delete(
            f"/api/v1/ignore-rules/{created.json()['id']}",
            headers=headers,
        )
        system_rule = next(rule for rule in listed.json()["rules"] if rule["is_system"])
        protected_update = client.patch(
            f"/api/v1/ignore-rules/{system_rule['id']}",
            headers=headers,
            json={"enabled": False},
        )
        invalid_scope = client.post(
            "/api/v1/ignore-rules",
            headers=headers,
            json={"type": "extension", "value": ".zip", "scope": "source"},
        )

    assert created.status_code == 201
    assert any(rule["id"] == created.json()["id"] for rule in listed.json()["rules"])
    assert tested.json()["matched_rule"]["id"] == created.json()["id"]
    assert disabled.json()["enabled"] is False
    assert deleted.json() == {"deleted": True, "rule_id": created.json()["id"]}
    assert protected_update.status_code == 403
    assert invalid_scope.status_code == 400


def _engine(tmp_path):
    home = tmp_path / "openmind"
    return OpenMindEngine(
        paths=AppPaths(
            home=home,
            config_path=home / "config.toml",
            sqlite_path=home / "openmind.sqlite",
            lancedb_path=home / "lancedb",
            logs_path=home / "logs",
        ),
        embeddings=HashEmbeddingProvider(dimension=16),
    )
