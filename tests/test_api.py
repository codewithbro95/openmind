from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from openmind import __version__
from openmind.api.app import create_app
from openmind.api.auth import ensure_api_token, rotate_api_token, token_path
from openmind.cli.main import app as cli_app
from openmind.core.config import AppPaths, ModelSettings, OpenMindConfig, ProviderSettings
from openmind.core.engine import OpenMindEngine
from openmind.core.errors import SourceRemovalBlockedError
from openmind.core.models import (
    FileRecord,
    IndexJob,
    SearchResult,
    Source,
    SourceRemovalResult,
    StatusSummary,
)
from openmind.providers.lmstudio.models import LMStudioModel

TOKEN = "test-token-abcdefghijklmnopqrstuvwxyz-123456"
FILE_ID = "file_0123456789abcdef"
SOURCE_ID = "src_0123456789ab"
API = "/api/v1"


class FakeLanceStore:
    def count_chunks(self):
        return 3

    def chunks_for_file(self, file_id):
        assert file_id == FILE_ID
        return [
            {
                "id": "chunk_1",
                "text": "Cabin packing notes",
                "chunk_index": 0,
                "title": "Holiday notes",
                "metadata": {"extension": ".md"},
            }
        ]


class FakeSQLiteStore:
    def __init__(self, record):
        self.record = record

    def file_by_id(self, file_id):
        return self.record if file_id == self.record.id else None


class FakeEngine:
    def __init__(self, tmp_path: Path):
        source_path = tmp_path / "documents"
        source_path.mkdir()
        file_path = source_path / "holiday.md"
        file_path.write_text("Cabin packing notes", encoding="utf-8")
        self.paths = AppPaths(
            home=tmp_path / ".openmind",
            config_path=tmp_path / ".openmind" / "config.toml",
            sqlite_path=tmp_path / ".openmind" / "openmind.sqlite",
            lancedb_path=tmp_path / ".openmind" / "lancedb",
            logs_path=tmp_path / ".openmind" / "logs",
        )
        self.config = OpenMindConfig(
            provider=ProviderSettings(name="lmstudio"),
            models=ModelSettings(chat_model="qwen", embedding_model="nomic"),
        )
        self.source = Source(
            id=SOURCE_ID,
            path=str(source_path),
            recursive=True,
            enabled=True,
            created_at="2026-07-19T10:00:00+00:00",
        )
        self.record = FileRecord(
            id=FILE_ID,
            source_id=SOURCE_ID,
            path=str(file_path),
            name=file_path.name,
            extension=".md",
            size=file_path.stat().st_size,
            modified_at=file_path.stat().st_mtime,
            content_hash="hash",
            status="indexed",
            indexed_at="2026-07-19T10:05:00+00:00",
        )
        self.sqlite = FakeSQLiteStore(self.record)
        self.lance = FakeLanceStore()
        self.job = None
        self.loaded = []

    def init(self):
        self.paths.ensure()
        return self.paths

    def reload_config_if_changed(self):
        return False

    def status(self):
        return StatusSummary(
            sources=1,
            enabled_sources=1,
            files=1,
            indexed_files=1,
            app_home=str(self.paths.home),
        )

    def index_job_status(self):
        return self.job

    def provider_status(self):
        return True, "LM Studio is reachable."

    def list_lmstudio_models(self):
        return [
            LMStudioModel(type="llm", key="qwen", display_name="Qwen"),
            LMStudioModel(type="embedding", key="nomic", display_name="Nomic"),
            LMStudioModel(
                type="llm",
                key="smolvlm",
                display_name="SmolVLM",
                capabilities={"vision": True},
            ),
        ]

    def lmstudio_client(self):
        return SimpleNamespace(load_model_if_needed=self._load_model)

    def _load_model(self, key):
        self.loaded.append(key)
        return {"model": key, "status": "loaded", "skipped": False}

    def load_configured_models(self):
        keys = [self.config.models.embedding_model]
        if self.config.models.chat_model:
            keys.insert(0, self.config.models.chat_model)
        if self.config.extraction.images.enabled:
            keys.append(self.config.extraction.images.model)
        return [self._load_model(key) for key in keys]

    def update_model_config(self, config, *, load=True):
        from openmind.core.models import ModelTransitionResult

        self.save_config(config)
        return ModelTransitionResult(
            unload_results=(
                [{"model": "qwen-old", "status": "unloaded", "skipped": False}]
                if load
                else []
            ),
            load_results=self.load_configured_models() if load else [],
        )

    def save_config(self, config):
        self.config = config

    def list_sources(self):
        return [self.source]

    def add_source(self, path, recursive=True):
        return Source(
            id="src_abcdef012345",
            path=str(Path(path).resolve()),
            recursive=recursive,
            enabled=True,
            created_at="2026-07-19T11:00:00+00:00",
        )

    def remove_source(self, source_id):
        if source_id != self.source.id:
            return None
        return SourceRemovalResult(
            source_id=self.source.id,
            source_path=self.source.path,
            files_removed=1,
            chunks_removed=3,
        )

    def start_index_job(self):
        self.job = IndexJob(id="job_123", status="pending")
        return self.job

    def pause_index_job(self):
        self.job = IndexJob(id="job_123", status="pause_requested") if self.job else None
        return self.job

    def resume_index_job(self):
        self.job = IndexJob(id="job_123", status="running") if self.job else None
        return self.job

    def stop_index_job(self):
        self.job = IndexJob(id="job_123", status="stop_requested") if self.job else None
        return self.job

    def search(self, query, limit=5):
        return [
            SearchResult(
                id="chunk_1",
                file_id=FILE_ID,
                source_id=SOURCE_ID,
                path=self.record.path,
                file_name=self.record.name,
                extension=".md",
                title="Holiday notes",
                text="Cabin packing notes",
                snippet="Cabin packing notes",
                score=0.91,
                chunk_index=0,
                metadata={"extension": ".md"},
            )
        ][:limit]

    def ask_with_sources(self, question, limit=5):
        return "Bring a jacket.", self.search(question, limit=limit)

    def ask_stream(self, question, limit=5):
        yield "Bring "
        yield "a jacket."

    def ask_stream_with_sources(self, question, limit=5):
        return self.ask_stream(question, limit=limit), self.search(question, limit=limit)


def auth_headers(token=TOKEN):
    return {"Authorization": f"Bearer {token}"}


def test_health_is_public_but_private_routes_require_token(tmp_path):
    app = create_app(engine=FakeEngine(tmp_path), api_token=TOKEN)
    with TestClient(app) as client:
        health = client.get("/health")
        missing = client.get(f"{API}/status")
        invalid = client.get(f"{API}/status", headers=auth_headers("wrong-token"))
        valid = client.get(f"{API}/status", headers=auth_headers())

    assert health.status_code == 200
    assert health.json() == {"status": "ok", "version": __version__}
    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert invalid.headers["www-authenticate"] == "Bearer"
    assert valid.status_code == 200
    assert valid.json()["indexed_chunks"] == 3


def test_running_api_refreshes_all_models_after_external_config_update(tmp_path):
    paths = AppPaths(
        home=tmp_path / ".openmind",
        config_path=tmp_path / ".openmind" / "config.toml",
        sqlite_path=tmp_path / ".openmind" / "openmind.sqlite",
        lancedb_path=tmp_path / ".openmind" / "lancedb",
        logs_path=tmp_path / ".openmind" / "logs",
    )
    initial = OpenMindConfig(
        provider=ProviderSettings(name="lmstudio", base_url="http://localhost:1234"),
        models=ModelSettings(chat_model="chat-old", embedding_model="embed-old"),
    )
    initial.extraction.images.model = "image-old"
    initial.save(paths.config_path)
    engine = OpenMindEngine(paths=paths)
    app = create_app(engine=engine, api_token=TOKEN)

    with TestClient(app) as client:
        before = client.get(f"{API}/status", headers=auth_headers())

        updated = initial.model_copy(deep=True)
        updated.provider.base_url = "http://localhost:2234"
        updated.models.chat_model = "chat-new"
        updated.models.embedding_model = "embed-new"
        updated.extraction.images.model = "image-new"
        updated.save(paths.config_path)

        after = client.get(f"{API}/status", headers=auth_headers())

    assert before.json()["chat_model"] == "chat-old"
    assert before.json()["embedding_model"] == "embed-old"
    assert before.json()["image_model"] == "image-old"
    assert after.json()["chat_model"] == "chat-new"
    assert after.json()["embedding_model"] == "embed-new"
    assert after.json()["image_model"] == "image-new"
    assert engine.answer_provider.model == "chat-new"
    assert engine.answer_provider.client.base_url == "http://localhost:2234"
    assert engine.embeddings.model == "embed-new"
    assert engine.embeddings.client.base_url == "http://localhost:2234"
    image_extractor = engine.extractors.for_path("example.png")
    assert image_extractor.description_provider.model_name == "image-new"
    assert image_extractor.description_provider.client.base_url == "http://localhost:2234"


def test_openapi_marks_private_routes_as_bearer_authenticated(tmp_path):
    app = create_app(engine=FakeEngine(tmp_path), api_token=TOKEN)
    with TestClient(app) as client:
        schema = client.get("/openapi.json").json()

    assert "security" not in schema["paths"]["/health"]["get"]
    assert schema["paths"][f"{API}/status"]["get"]["security"]
    assert schema["paths"][f"{API}/search"]["post"]["security"]
    assert "OpenMind API token" in schema["components"]["securitySchemes"]


def test_models_sources_and_index_controls(tmp_path):
    engine = FakeEngine(tmp_path)
    app = create_app(engine=engine, api_token=TOKEN)
    with TestClient(app) as client:
        models = client.get(f"{API}/models", headers=auth_headers())
        selection = client.put(
            f"{API}/models/selection",
            headers=auth_headers(),
            json={
                "chat_model": "qwen",
                "embedding_model": "nomic",
                "image_model": "smolvlm",
                "load": False,
            },
        )
        source = client.post(
            f"{API}/sources",
            headers=auth_headers(),
            json={"path": str(tmp_path), "recursive": False},
        )
        started = client.post(f"{API}/index/start", headers=auth_headers())
        paused = client.post(f"{API}/index/pause", headers=auth_headers())
        resumed = client.post(f"{API}/index/resume", headers=auth_headers())
        stopped = client.post(f"{API}/index/stop", headers=auth_headers())
        removed = client.delete(f"{API}/sources/{SOURCE_ID}", headers=auth_headers())

    assert models.status_code == 200
    assert models.json()["image_models"][0]["key"] == "smolvlm"
    assert selection.status_code == 200
    assert selection.json()["unload_results"] == []
    assert selection.json()["load_results"] == []
    assert source.status_code == 201
    assert source.json()["recursive"] is False
    assert started.status_code == 202
    assert paused.json()["state"] == "pause_requested"
    assert resumed.json()["state"] == "running"
    assert stopped.json()["state"] == "stop_requested"
    assert removed.status_code == 200
    assert removed.json() == {
        "source_id": SOURCE_ID,
        "source_path": engine.source.path,
        "files_removed": 1,
        "chunks_removed": 3,
        "user_files_deleted": False,
    }


def test_model_selection_api_reports_unload_and_load_results(tmp_path):
    engine = FakeEngine(tmp_path)
    app = create_app(engine=engine, api_token=TOKEN)

    with TestClient(app) as client:
        response = client.put(
            f"{API}/models/selection",
            headers=auth_headers(),
            json={
                "chat_model": "qwen",
                "embedding_model": "nomic",
                "image_model": None,
                "load": True,
            },
        )

    assert response.status_code == 200
    assert response.json()["unload_results"] == [
        {"model": "qwen-old", "status": "unloaded", "skipped": False}
    ]
    assert [result["model"] for result in response.json()["load_results"]] == [
        "qwen",
        "nomic",
    ]


def test_source_removal_returns_conflict_during_indexing(tmp_path):
    engine = FakeEngine(tmp_path)

    def blocked(source_id):
        raise SourceRemovalBlockedError("Stop indexing before removing this source.")

    engine.remove_source = blocked
    app = create_app(engine=engine, api_token=TOKEN)

    with TestClient(app) as client:
        response = client.delete(f"{API}/sources/{SOURCE_ID}", headers=auth_headers())

    assert response.status_code == 409
    assert response.json()["detail"] == "Stop indexing before removing this source."


def test_search_ask_stream_document_and_safe_open(tmp_path):
    engine = FakeEngine(tmp_path)
    opened = []
    app = create_app(
        engine=engine,
        api_token=TOKEN,
        file_opener=lambda path: opened.append(path),
    )
    with TestClient(app) as client:
        search = client.post(
            f"{API}/search",
            headers=auth_headers(),
            json={"query": "cabin", "limit": 5},
        )
        ask = client.post(
            f"{API}/ask",
            headers=auth_headers(),
            json={"question": "What should I pack?"},
        )
        stream = client.post(
            f"{API}/ask/stream",
            headers=auth_headers(),
            json={"question": "What should I pack?"},
        )
        document = client.get(f"{API}/documents/{FILE_ID}", headers=auth_headers())
        opened_response = client.post(
            f"{API}/actions/open",
            headers=auth_headers(),
            json={"file_id": FILE_ID},
        )

    assert search.status_code == 200
    assert search.json()["results"][0]["file_id"] == FILE_ID
    assert search.json()["results"][0]["source_type"] == "md"
    assert ask.json()["answer"] == "Bring a jacket."
    assert ask.json()["sources"][0]["path"] == engine.record.path
    assert "event: delta" in stream.text
    assert "event: sources" in stream.text
    assert FILE_ID in stream.text
    assert "event: done" in stream.text
    assert document.json()["chunks"][0]["text"] == "Cabin packing notes"
    assert opened_response.status_code == 200
    assert opened == [Path(engine.record.path).resolve()]


def test_open_action_rejects_file_outside_enabled_sources(tmp_path):
    engine = FakeEngine(tmp_path)
    outside = tmp_path / "outside.md"
    outside.write_text("private", encoding="utf-8")
    engine.record.path = str(outside)
    app = create_app(engine=engine, api_token=TOKEN, file_opener=lambda path: None)

    with TestClient(app) as client:
        response = client.post(
            f"{API}/actions/open",
            headers=auth_headers(),
            json={"file_id": FILE_ID},
        )

    assert response.status_code == 403


def test_api_rejects_empty_queries_extra_fields_and_invalid_file_ids(tmp_path):
    app = create_app(engine=FakeEngine(tmp_path), api_token=TOKEN)
    with TestClient(app) as client:
        empty = client.post(f"{API}/search", headers=auth_headers(), json={"query": "   "})
        extra = client.post(
            f"{API}/search",
            headers=auth_headers(),
            json={"query": "cabin", "raw_vectors": True},
        )
        invalid_file = client.post(
            f"{API}/actions/open",
            headers=auth_headers(),
            json={"file_id": "../../etc/passwd"},
        )

    assert empty.status_code == 422
    assert extra.status_code == 422
    assert invalid_file.status_code == 422


def test_api_token_is_private_and_rotatable(tmp_path):
    home = tmp_path / ".openmind"

    first = ensure_api_token(home)
    second = ensure_api_token(home)
    rotated = rotate_api_token(home)

    assert first == second
    assert rotated != first
    assert token_path(home).read_text(encoding="utf-8").strip() == rotated
    if os.name != "nt":
        assert token_path(home).stat().st_mode & 0o777 == 0o600


def test_running_api_picks_up_rotated_token(tmp_path):
    engine = FakeEngine(tmp_path)
    original = ensure_api_token(engine.paths.home)
    app = create_app(engine=engine)

    with TestClient(app) as client:
        before = client.get(f"{API}/status", headers=auth_headers(original))
        rotated = rotate_api_token(engine.paths.home)
        stale = client.get(f"{API}/status", headers=auth_headers(original))
        current = client.get(f"{API}/status", headers=auth_headers(rotated))

    assert before.status_code == 200
    assert stale.status_code == 401
    assert current.status_code == 200


def test_app_rejects_wildcard_cors_even_outside_cli(tmp_path):
    with pytest.raises(ValueError, match="exact http\\(s\\) origins"):
        create_app(
            engine=FakeEngine(tmp_path),
            api_token=TOKEN,
            allowed_origins=["*"],
        )


def test_serve_command_binds_to_loopback_and_rejects_wildcard_cors(monkeypatch, tmp_path):
    engine = FakeEngine(tmp_path)
    uvicorn_calls = []
    monkeypatch.setattr("openmind.cli.main.engine", lambda: engine)
    monkeypatch.setattr("uvicorn.run", lambda api, **kwargs: uvicorn_calls.append(kwargs))

    served = CliRunner().invoke(cli_app, ["serve", "--port", "9876"])
    wildcard = CliRunner().invoke(cli_app, ["serve", "--allow-origin", "*"])

    assert served.exit_code == 0
    assert uvicorn_calls == [
        {
            "host": "127.0.0.1",
            "port": 9876,
            "log_level": "info",
            "access_log": False,
        }
    ]
    assert wildcard.exit_code != 0
    assert "exact http(s) origins" in wildcard.output
