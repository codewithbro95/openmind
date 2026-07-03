import json
import urllib.error

import pytest

from openmind.core.models import SearchResult
from openmind.llm.answer import ContextOnlyAnswerProvider
from openmind.providers.lmstudio.client import LMStudioClient
from openmind.providers.lmstudio.errors import LMStudioConnectionError
from openmind.providers.lmstudio.llm import LMStudioLLMProvider
from openmind.providers.lmstudio.models import split_models


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_lmstudio_model_listing_and_split(monkeypatch):
    def fake_urlopen(request, timeout):
        assert request.full_url == "http://localhost:1234/api/v1/models"
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
                        "loaded_instances": [{"id": "nomic", "config": {}}],
                    },
                ]
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    models = LMStudioClient().list_models()
    chat_models, embedding_models = split_models(models)

    assert chat_models[0].key == "qwen"
    assert embedding_models[0].key == "nomic"
    assert embedding_models[0].is_loaded is True


def test_lmstudio_load_model_posts_model_key(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse({"status": "loaded", "type": "embedding", "instance_id": "nomic"})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    response = LMStudioClient().load_model("nomic", context_length=2048)

    assert captured["url"] == "http://localhost:1234/api/v1/models/load"
    assert captured["body"] == {"model": "nomic", "context_length": 2048}
    assert response["status"] == "loaded"


def test_lmstudio_client_reports_unreachable(monkeypatch):
    def fake_urlopen(request, timeout):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    with pytest.raises(LMStudioConnectionError) as exc:
        LMStudioClient().list_models()

    assert "lms server start" in str(exc.value)


def test_lmstudio_answer_returns_unreachable_message():
    class BrokenClient:
        def is_model_loaded(self, model):
            return True

        def chat(self, model, messages):
            raise LMStudioConnectionError("LM Studio is not reachable at http://localhost:1234.")

    result = SearchResult(
        id="chunk_1",
        path="/docs/thesis.md",
        file_name="thesis.md",
        title="thesis",
        text="Thesis notes",
        snippet="Thesis notes",
        score=0.9,
        chunk_index=0,
    )

    answer = LMStudioLLMProvider(BrokenClient(), "qwen").answer("What did I write?", [result])

    assert "LM Studio is not reachable" in answer


def test_lmstudio_answer_reports_unloaded_chat_model():
    class UnloadedClient:
        def is_model_loaded(self, model):
            return False

    result = SearchResult(
        id="chunk_1",
        path="/docs/thesis.md",
        file_name="thesis.md",
        title="thesis",
        text="Thesis notes",
        snippet="Thesis notes",
        score=0.9,
        chunk_index=0,
    )

    answer = LMStudioLLMProvider(UnloadedClient(), "qwen").answer("What did I write?", [result])

    assert "selected chat model is not loaded" in answer


def test_context_only_answer_still_available_for_dev_fallback():
    assert "did not find" in ContextOnlyAnswerProvider().answer("anything?", [])
