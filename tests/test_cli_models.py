import json

from typer.testing import CliRunner

from openmind.cli.main import app
from openmind.core.config import ModelSettings, OpenMindConfig, ProviderSettings


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_models_update_saves_selected_lmstudio_models(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENMIND_HOME", str(tmp_path))
    loaded_models = []

    def fake_urlopen(request, timeout):
        if request.full_url.endswith("/api/v1/models"):
            return FakeResponse(
                {
                    "models": [
                        {
                            "type": "llm",
                            "key": "qwen",
                            "display_name": "Qwen",
                            "loaded_instances": [],
                        },
                        {
                            "type": "llm",
                            "key": "gemma",
                            "display_name": "Gemma",
                            "loaded_instances": [],
                        },
                        {
                            "type": "embedding",
                            "key": "nomic",
                            "display_name": "Nomic Embed",
                            "loaded_instances": [],
                        },
                    ]
                }
            )
        if request.full_url.endswith("/api/v1/models/load"):
            body = json.loads(request.data.decode("utf-8"))
            loaded_models.append(body["model"])
            return FakeResponse({"status": "loaded"})
        raise AssertionError(f"Unexpected URL: {request.full_url}")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    result = CliRunner().invoke(app, ["models", "update"], input="1\n\n2\n1\n")

    assert result.exit_code == 0
    config = OpenMindConfig.load(tmp_path / "config.toml")
    assert config.provider.name == "lmstudio"
    assert config.models.chat_model == "gemma"
    assert config.models.embedding_model == "nomic"
    assert loaded_models == ["gemma", "nomic"]
    assert config.extraction.images.enabled is False


def test_models_update_saves_selected_image_description_model(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENMIND_HOME", str(tmp_path))
    loaded_models = []

    def fake_urlopen(request, timeout):
        if request.full_url.endswith("/api/v1/models"):
            return FakeResponse(
                {
                    "models": [
                        {
                            "type": "llm",
                            "key": "qwen",
                            "display_name": "Qwen",
                            "loaded_instances": [],
                        },
                        {
                            "type": "llm",
                            "key": "smolvlm",
                            "display_name": "SmolVLM",
                            "capabilities": {"vision": True},
                            "loaded_instances": [],
                        },
                        {
                            "type": "embedding",
                            "key": "nomic",
                            "display_name": "Nomic Embed",
                            "loaded_instances": [],
                        },
                    ]
                }
            )
        if request.full_url.endswith("/api/v1/models/load"):
            body = json.loads(request.data.decode("utf-8"))
            loaded_models.append(body["model"])
            return FakeResponse({"status": "loaded"})
        raise AssertionError(f"Unexpected URL: {request.full_url}")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    result = CliRunner().invoke(app, ["models", "update"], input="1\n\n1\n1\n1\n")

    assert result.exit_code == 0
    config = OpenMindConfig.load(tmp_path / "config.toml")
    assert config.models.chat_model == "qwen"
    assert config.models.embedding_model == "nomic"
    assert config.extraction.images.enabled is True
    assert config.extraction.images.model == "smolvlm"
    assert loaded_models == ["qwen", "nomic", "smolvlm"]


def test_models_update_can_keep_existing_models_without_loading(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENMIND_HOME", str(tmp_path))
    OpenMindConfig(
        provider=ProviderSettings(name="lmstudio", base_url="http://localhost:1234"),
        models=ModelSettings(chat_model="qwen", embedding_model="nomic"),
    ).save(tmp_path / "config.toml")

    def fake_urlopen(request, timeout):
        if request.full_url.endswith("/api/v1/models"):
            return FakeResponse(
                {
                    "models": [
                        {
                            "type": "llm",
                            "key": "qwen",
                            "display_name": "Qwen",
                            "loaded_instances": [],
                        },
                        {
                            "type": "embedding",
                            "key": "nomic",
                            "display_name": "Nomic Embed",
                            "loaded_instances": [],
                        },
                    ]
                }
            )
        raise AssertionError(f"Unexpected URL: {request.full_url}")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    result = CliRunner().invoke(
        app,
        ["models", "update", "--no-load"],
        input="1\n\n\n\n",
    )

    assert result.exit_code == 0
    config = OpenMindConfig.load(tmp_path / "config.toml")
    assert config.models.chat_model == "qwen"
    assert config.models.embedding_model == "nomic"


def test_models_update_skips_models_that_are_already_loaded(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENMIND_HOME", str(tmp_path))

    def fake_urlopen(request, timeout):
        if request.full_url.endswith("/api/v1/models"):
            return FakeResponse(
                {
                    "models": [
                        {
                            "type": "llm",
                            "key": "qwen",
                            "display_name": "Qwen",
                            "loaded_instances": [{"id": "qwen", "config": {}}],
                        },
                        {
                            "type": "embedding",
                            "key": "nomic",
                            "display_name": "Nomic Embed",
                            "loaded_instances": [{"id": "nomic", "config": {}}],
                        },
                    ]
                }
            )
        if request.full_url.endswith("/api/v1/models/load"):
            raise AssertionError("Already loaded models should not be loaded again")
        raise AssertionError(f"Unexpected URL: {request.full_url}")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    result = CliRunner().invoke(app, ["models", "update"], input="1\n\n1\n1\n")

    assert result.exit_code == 0
    assert "already loaded" in result.output
