import json
import socket
import urllib.error

import pytest

from openmind.core.models import SearchResult
from openmind.llm.answer import ContextOnlyAnswerProvider
from openmind.providers.lmstudio.client import LMStudioChatResult, LMStudioClient
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

    def __iter__(self):
        if isinstance(self.payload, list):
            for line in self.payload:
                yield line.encode("utf-8")
            return
        yield json.dumps(self.payload).encode("utf-8")


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


def test_lmstudio_load_model_if_needed_skips_loaded_model(monkeypatch):
    requested_urls = []

    def fake_urlopen(request, timeout):
        requested_urls.append(request.full_url)
        assert request.full_url == "http://localhost:1234/api/v1/models"
        return FakeResponse(
            {
                "models": [
                    {
                        "type": "embedding",
                        "key": "nomic",
                        "display_name": "Nomic Embed",
                        "loaded_instances": [{"id": "nomic", "config": {}}],
                    }
                ]
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    response = LMStudioClient().load_model_if_needed("nomic")

    assert response["status"] == "already_loaded"
    assert response["skipped"] is True
    assert requested_urls == ["http://localhost:1234/api/v1/models"]


def test_lmstudio_client_reports_unreachable(monkeypatch):
    def fake_urlopen(request, timeout):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    with pytest.raises(LMStudioConnectionError) as exc:
        LMStudioClient().list_models()

    assert "lms server start" in str(exc.value)


def test_lmstudio_client_reports_timeout(monkeypatch):
    def fake_urlopen(request, timeout):
        raise socket.timeout("timed out")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    with pytest.raises(LMStudioConnectionError) as exc:
        LMStudioClient(timeout=0.1).embed("nomic", ["Portugal\nvisa"])

    assert "Timed out waiting for LM Studio" in str(exc.value)


def test_lmstudio_chat_extracts_think_block(monkeypatch):
    def fake_urlopen(request, timeout):
        return FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": "<think>checking sources</think>The answer is grounded."
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    result = LMStudioClient().chat("thinking-model", [{"role": "user", "content": "Hi"}])

    assert result.reasoning == "checking sources"
    assert result.content == "The answer is grounded."


def test_lmstudio_chat_stream_parses_sse_deltas(monkeypatch):
    def fake_urlopen(request, timeout):
        body = json.loads(request.data.decode("utf-8"))
        assert body["stream"] is True
        return FakeResponse(
            [
                'data: {"choices":[{"delta":{"content":"Hello"}}]}\n',
                "\n",
                'data: {"choices":[{"delta":{"content":" world"}}]}\n',
                "\n",
                "data: [DONE]\n",
                "\n",
            ]
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    deltas = list(LMStudioClient().chat_stream("model", [{"role": "user", "content": "Hi"}]))

    assert [delta.content for delta in deltas] == ["Hello", " world"]


def test_lmstudio_responses_extracts_reasoning(monkeypatch):
    def fake_urlopen(request, timeout):
        assert request.full_url == "http://localhost:1234/v1/responses"
        return FakeResponse(
            {
                "output": [
                    {"type": "reasoning", "summary": [{"text": "I checked the context."}]},
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "Use the visa notes."}],
                    },
                ]
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    result = LMStudioClient().respond_with_reasoning(
        "thinking-model",
        [{"role": "user", "content": "What should I use?"}],
    )

    assert "checked the context" in result.reasoning
    assert result.content == "Use the visa notes."


def test_lmstudio_response_stream_parses_reasoning_and_text(monkeypatch):
    def fake_urlopen(request, timeout):
        body = json.loads(request.data.decode("utf-8"))
        assert body["stream"] is True
        return FakeResponse(
            [
                'data: {"type":"response.reasoning_text.delta","delta":"checking"}\n',
                "\n",
                'data: {"type":"response.output_text.delta","delta":"Use"}\n',
                "\n",
                'data: {"type":"response.output_text.delta","delta":" notes"}\n',
                "\n",
                "data: [DONE]\n",
                "\n",
            ]
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    deltas = list(
        LMStudioClient().respond_stream("model", [{"role": "user", "content": "Hi"}])
    )

    assert deltas[0].reasoning == "checking"
    assert "".join(delta.content for delta in deltas) == "Use notes"


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


def test_lmstudio_answer_can_show_provider_returned_thinking():
    class ThinkingClient:
        def is_model_loaded(self, model):
            return True

        def respond_with_reasoning(self, model, messages):
            return LMStudioChatResult(content="Use the visa notes.", reasoning="I checked context.")

    result = SearchResult(
        id="chunk_1",
        path="/docs/visa.md",
        file_name="visa.md",
        title="visa",
        text="Visa notes",
        snippet="Visa notes",
        score=0.9,
        chunk_index=0,
    )

    answer = LMStudioLLMProvider(ThinkingClient(), "qwen").answer(
        "What did I write?",
        [result],
        show_thinking=True,
    )

    assert "Thinking:" in answer
    assert "I checked context." in answer
    assert "Use the visa notes." in answer


def test_lmstudio_stream_answer_streams_content_then_sources():
    class StreamingClient:
        def is_model_loaded(self, model):
            return True

        def chat_stream(self, model, messages):
            yield LMStudioChatResult(content="Use")
            yield LMStudioChatResult(content=" notes")

    result = SearchResult(
        id="chunk_1",
        path="/docs/visa.md",
        file_name="visa.md",
        title="visa",
        text="Visa notes",
        snippet="Visa notes",
        score=0.9,
        chunk_index=0,
    )

    chunks = list(LMStudioLLMProvider(StreamingClient(), "qwen").stream_answer("Q?", [result]))

    assert chunks[0] == "Use"
    assert chunks[1] == " notes"
    assert "Sources:" in chunks[-1]


def test_lmstudio_messages_include_session_history():
    provider = LMStudioLLMProvider(LMStudioClient(), "qwen")
    result = SearchResult(
        id="chunk_1",
        path="/docs/visa.md",
        file_name="visa.md",
        title="visa",
        text="Visa notes",
        snippet="Visa notes",
        score=0.9,
        chunk_index=0,
    )

    messages = provider._messages(
        "What about that?",
        [result],
        history=[
            {"role": "user", "content": "Tell me about Portugal."},
            {"role": "assistant", "content": "You have visa notes."},
        ],
    )

    assert messages[1] == {"role": "user", "content": "Tell me about Portugal."}
    assert messages[2] == {"role": "assistant", "content": "You have visa notes."}
    assert "What about that?" in messages[-1]["content"]


def test_context_only_answer_still_available_for_dev_fallback():
    assert "did not find" in ContextOnlyAnswerProvider().answer("anything?", [])
