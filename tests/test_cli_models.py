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


def mock_prompt_answers(monkeypatch, *answers):
    selected = iter(answers)
    monkeypatch.setattr(
        "openmind.cli.main._select_prompt",
        lambda *args, **kwargs: next(selected),
    )
    monkeypatch.setattr(
        "openmind.cli.main._text_prompt",
        lambda message, default="": default,
    )


def test_models_update_saves_selected_lmstudio_models(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENMIND_HOME", str(tmp_path))
    mock_prompt_answers(monkeypatch, "lmstudio", "gemma", "nomic")
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

    result = CliRunner().invoke(app, ["models", "update"])

    assert result.exit_code == 0
    config = OpenMindConfig.load(tmp_path / "config.toml")
    assert config.provider.name == "lmstudio"
    assert config.models.chat_model == "gemma"
    assert config.models.embedding_model == "nomic"
    assert loaded_models == ["gemma", "nomic"]
    assert config.extraction.images.enabled is False


def test_models_update_saves_selected_image_description_model(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENMIND_HOME", str(tmp_path))
    mock_prompt_answers(monkeypatch, "lmstudio", "qwen", "nomic", "smolvlm")
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

    result = CliRunner().invoke(app, ["models", "update"])

    assert result.exit_code == 0
    config = OpenMindConfig.load(tmp_path / "config.toml")
    assert config.models.chat_model == "qwen"
    assert config.models.embedding_model == "nomic"
    assert config.extraction.images.enabled is True
    assert config.extraction.images.model == "smolvlm"
    assert loaded_models == ["qwen", "nomic", "smolvlm"]


def test_models_update_can_keep_existing_models_without_loading(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENMIND_HOME", str(tmp_path))
    mock_prompt_answers(monkeypatch, "lmstudio", "qwen", "nomic")
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
    )

    assert result.exit_code == 0
    config = OpenMindConfig.load(tmp_path / "config.toml")
    assert config.models.chat_model == "qwen"
    assert config.models.embedding_model == "nomic"


def test_models_update_skips_models_that_are_already_loaded(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENMIND_HOME", str(tmp_path))
    mock_prompt_answers(monkeypatch, "lmstudio", "qwen", "nomic")
    config = OpenMindConfig(
        provider=ProviderSettings(name="lmstudio", base_url="http://localhost:1234"),
        models=ModelSettings(chat_model="qwen", embedding_model="nomic"),
    )
    config.extraction.images.enabled = False
    config.save(tmp_path / "config.toml")

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

    result = CliRunner().invoke(app, ["models", "update"])

    assert result.exit_code == 0
    assert "already loaded" in result.output


def test_models_update_unloads_replaced_models_before_loading_new_ones(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENMIND_HOME", str(tmp_path))
    mock_prompt_answers(monkeypatch, "lmstudio", "qwen-new", "embed-new")
    OpenMindConfig(
        provider=ProviderSettings(name="lmstudio", base_url="http://localhost:1234"),
        models=ModelSettings(chat_model="qwen-old", embedding_model="embed-old"),
    ).save(tmp_path / "config.toml")
    operations = []

    def fake_urlopen(request, timeout):
        if request.full_url.endswith("/api/v1/models"):
            return FakeResponse(
                {
                    "models": [
                        {
                            "type": "llm",
                            "key": "qwen-old",
                            "display_name": "Qwen Old",
                            "loaded_instances": [{"id": "qwen-old:1", "config": {}}],
                        },
                        {
                            "type": "embedding",
                            "key": "embed-old",
                            "display_name": "Embed Old",
                            "loaded_instances": [{"id": "embed-old:1", "config": {}}],
                        },
                        {
                            "type": "llm",
                            "key": "qwen-new",
                            "display_name": "Qwen New",
                            "loaded_instances": [],
                        },
                        {
                            "type": "embedding",
                            "key": "embed-new",
                            "display_name": "Embed New",
                            "loaded_instances": [],
                        },
                    ]
                }
            )
        body = json.loads(request.data.decode("utf-8"))
        if request.full_url.endswith("/api/v1/models/unload"):
            operations.append(("unload", body["instance_id"]))
            return FakeResponse({"status": "unloaded"})
        if request.full_url.endswith("/api/v1/models/load"):
            operations.append(("load", body["model"]))
            return FakeResponse({"status": "loaded"})
        raise AssertionError(f"Unexpected URL: {request.full_url}")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    result = CliRunner().invoke(app, ["models", "update"])

    assert result.exit_code == 0
    assert operations[:2] == [
        ("unload", "embed-old:1"),
        ("unload", "qwen-old:1"),
    ]
    assert operations[2:] == [("load", "qwen-new"), ("load", "embed-new")]
    assert "Previous model unloaded" in result.output


def test_models_update_no_load_does_not_change_loaded_instances(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENMIND_HOME", str(tmp_path))
    mock_prompt_answers(monkeypatch, "lmstudio", "qwen-new", "embed-new")
    OpenMindConfig(
        provider=ProviderSettings(name="lmstudio", base_url="http://localhost:1234"),
        models=ModelSettings(chat_model="qwen-old", embedding_model="embed-old"),
    ).save(tmp_path / "config.toml")

    def fake_urlopen(request, timeout):
        if request.full_url.endswith("/api/v1/models"):
            return FakeResponse(
                {
                    "models": [
                        {"type": "llm", "key": "qwen-new", "display_name": "Qwen New"},
                        {
                            "type": "embedding",
                            "key": "embed-new",
                            "display_name": "Embed New",
                        },
                    ]
                }
            )
        raise AssertionError("--no-load must not load or unload model instances")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    result = CliRunner().invoke(app, ["models", "update", "--no-load"])

    assert result.exit_code == 0
    config = OpenMindConfig.load(tmp_path / "config.toml")
    assert config.models.chat_model == "qwen-new"
    assert config.models.embedding_model == "embed-new"
