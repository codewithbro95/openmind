import json
import socket
import urllib.error

import pytest

from openmind.core.models import SearchResult
from openmind.llm.answer import ContextOnlyAnswerProvider
from openmind.llm.session import ChatSession
from openmind.providers.lmstudio.client import (
    LMStudioChatResult,
    LMStudioClient,
    LMStudioStreamDelta,
)
from openmind.providers.lmstudio.errors import LMStudioConnectionError, LMStudioModelError
from openmind.providers.lmstudio.images import LMStudioImageDescriptionProvider
from openmind.providers.lmstudio.llm import LMStudioLLMProvider
from openmind.providers.lmstudio.models import split_models, vision_models


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
                    {
                        "type": "llm",
                        "key": "smolvlm",
                        "display_name": "SmolVLM",
                        "capabilities": {"vision": True},
                        "loaded_instances": [],
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
    assert vision_models(models)[0].key == "smolvlm"


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


def test_lmstudio_native_chat_uses_previous_response_id(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse(
            {
                "output": [
                    {"type": "reasoning", "content": "checked"},
                    {"type": "message", "content": "Use the notes."},
                ],
                "response_id": "resp_next",
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    result = LMStudioClient().native_chat(
        "qwen",
        "Question and evidence",
        "System prompt",
        previous_response_id="resp_previous",
        store=True,
    )

    assert captured["url"] == "http://localhost:1234/api/v1/chat"
    assert captured["body"]["previous_response_id"] == "resp_previous"
    assert captured["body"]["store"] is True
    assert result.content == "Use the notes."
    assert result.reasoning == "checked"
    assert result.response_id == "resp_next"


def test_lmstudio_native_chat_stream_parses_content_reasoning_and_response_id(monkeypatch):
    def fake_urlopen(request, timeout):
        return FakeResponse(
            [
                'event: reasoning.delta\n',
                'data: {"type":"reasoning.delta","content":"checked"}\n',
                "\n",
                'event: message.delta\n',
                'data: {"type":"message.delta","content":"Use notes"}\n',
                "\n",
                'event: chat.end\n',
                'data: {"type":"chat.end","result":{"response_id":"resp_next"}}\n',
                "\n",
            ]
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    deltas = list(
        LMStudioClient().native_chat_stream(
            "qwen",
            "Question and evidence",
            "System prompt",
            store=True,
        )
    )

    assert deltas == [
        LMStudioStreamDelta(reasoning="checked"),
        LMStudioStreamDelta(content="Use notes"),
        LMStudioStreamDelta(response_id="resp_next"),
    ]


def test_lmstudio_native_chat_maps_reasoning_boolean_to_model_setting(monkeypatch):
    requests = []

    def fake_urlopen(request, timeout):
        requests.append((request.full_url, json.loads(request.data.decode("utf-8")) if request.data else None))
        if request.full_url.endswith("/api/v1/models"):
            return FakeResponse(
                {
                    "models": [
                        {
                            "type": "llm",
                            "key": "reasoner",
                            "display_name": "Reasoner",
                            "capabilities": {
                                "reasoning": {
                                    "allowed_options": ["off", "low", "medium", "high"],
                                    "default": "high",
                                }
                            },
                        }
                    ]
                }
            )
        return FakeResponse({"output": [{"type": "message", "content": "Done."}]})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = LMStudioClient()

    client.native_chat("reasoner", "Question", None, reasoning=True)
    client.native_chat("reasoner", "Question", None, reasoning=False)

    chat_payloads = [body for url, body in requests if url.endswith("/api/v1/chat")]
    assert chat_payloads[0]["reasoning"] == "high"
    assert chat_payloads[1]["reasoning"] == "off"


def test_lmstudio_rejects_enabled_reasoning_for_non_reasoning_model(monkeypatch):
    def fake_urlopen(request, timeout):
        assert request.full_url.endswith("/api/v1/models")
        return FakeResponse(
            {
                "models": [
                    {"type": "llm", "key": "standard", "display_name": "Standard"}
                ]
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    with pytest.raises(LMStudioModelError, match="does not support reasoning"):
        LMStudioClient().native_chat("standard", "Question", None, reasoning=True)


def test_lmstudio_omits_reasoning_for_non_reasoning_model_when_disabled(monkeypatch):
    requests = []

    def fake_urlopen(request, timeout):
        requests.append((request.full_url, json.loads(request.data.decode("utf-8")) if request.data else None))
        if request.full_url.endswith("/api/v1/models"):
            return FakeResponse(
                {
                    "models": [
                        {"type": "llm", "key": "standard", "display_name": "Standard"}
                    ]
                }
            )
        return FakeResponse({"output": [{"type": "message", "content": "Done."}]})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    LMStudioClient().native_chat("standard", "Question", None, reasoning=False)

    chat_payload = next(body for url, body in requests if url.endswith("/api/v1/chat"))
    assert "reasoning" not in chat_payload


def test_lmstudio_unloads_every_loaded_instance_for_selected_models(monkeypatch):
    unloaded_instances = []

    def fake_urlopen(request, timeout):
        if request.full_url.endswith("/api/v1/models"):
            return FakeResponse(
                {
                    "models": [
                        {
                            "type": "llm",
                            "key": "qwen-old",
                            "display_name": "Qwen Old",
                            "loaded_instances": [
                                {"id": "qwen-old:1", "config": {}},
                                {"id": "qwen-old:2", "config": {}},
                            ],
                        },
                        {
                            "type": "llm",
                            "key": "unrelated",
                            "display_name": "Unrelated",
                            "loaded_instances": [{"id": "unrelated:1", "config": {}}],
                        },
                    ]
                }
            )
        if request.full_url.endswith("/api/v1/models/unload"):
            body = json.loads(request.data.decode("utf-8"))
            unloaded_instances.append(body["instance_id"])
            return FakeResponse({"status": "unloaded"})
        raise AssertionError(f"Unexpected URL: {request.full_url}")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    results = LMStudioClient().unload_models_if_loaded({"qwen-old"})

    assert unloaded_instances == ["qwen-old:1", "qwen-old:2"]
    assert results == [
        {
            "model": "qwen-old",
            "status": "unloaded",
            "skipped": False,
            "instance_ids": ["qwen-old:1", "qwen-old:2"],
        }
    ]


def test_lmstudio_skips_unload_when_model_is_not_loaded(monkeypatch):
    def fake_urlopen(request, timeout):
        assert request.full_url.endswith("/api/v1/models")
        return FakeResponse(
            {
                "models": [
                    {
                        "type": "llm",
                        "key": "qwen-old",
                        "display_name": "Qwen Old",
                        "loaded_instances": [],
                    }
                ]
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    results = LMStudioClient().unload_models_if_loaded({"qwen-old", "missing"})

    assert results == [
        {"model": "missing", "status": "not_available", "skipped": True},
        {"model": "qwen-old", "status": "already_unloaded", "skipped": True},
    ]


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
        LMStudioClient(timeout=0.1).embed("nomic", ["holiday\nplan"])

    assert "Timed out waiting for LM Studio" in str(exc.value)


def test_lmstudio_chat_extracts_think_block(monkeypatch):
    def fake_urlopen(request, timeout):
        body = json.loads(request.data.decode("utf-8"))
        assert body["max_tokens"] == 700
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


def test_lmstudio_image_description_provider_sends_multimodal_request(tmp_path):
    path = tmp_path / "image.png"
    path.write_bytes(b"fake image bytes")

    class FakeClient:
        def __init__(self):
            self.loaded = []
            self.messages = None
            self.max_tokens = None

        def load_model_if_needed(self, model):
            self.loaded.append(model)
            return {"status": "already_loaded", "skipped": True}

        def chat(self, model, messages, max_tokens):
            self.messages = messages
            self.max_tokens = max_tokens
            return LMStudioChatResult(content="A small test image.")

    client = FakeClient()
    provider = LMStudioImageDescriptionProvider(client=client, model="smolvlm")

    description = provider.describe(path, "Describe this image.", 80)

    assert description == "A small test image."
    assert client.loaded == ["smolvlm"]
    assert client.max_tokens == 80
    content = client.messages[0]["content"]
    assert content[0] == {"type": "text", "text": "Describe this image."}
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_lmstudio_chat_stream_parses_sse_deltas(monkeypatch):
    def fake_urlopen(request, timeout):
        body = json.loads(request.data.decode("utf-8"))
        assert body["stream"] is True
        assert body["max_tokens"] == 700
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
        body = json.loads(request.data.decode("utf-8"))
        assert body["max_output_tokens"] == 700
        return FakeResponse(
            {
                "output": [
                    {"type": "reasoning", "summary": [{"text": "I checked the context."}]},
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "Use the planning notes."}],
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
    assert result.content == "Use the planning notes."


def test_lmstudio_response_stream_parses_reasoning_and_text(monkeypatch):
    def fake_urlopen(request, timeout):
        body = json.loads(request.data.decode("utf-8"))
        assert body["stream"] is True
        assert body["max_output_tokens"] == 700
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
        def native_chat(self, *args, **kwargs):
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


def test_lmstudio_answer_reports_native_api_model_error():
    class UnloadedClient:
        def native_chat(self, *args, **kwargs):
            raise LMStudioModelError("Selected model is not available: qwen")

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

    assert "Selected model is not available" in answer


def test_lmstudio_answer_can_enable_and_show_provider_reasoning():
    class ThinkingClient:
        def native_chat(self, *args, **kwargs):
            assert kwargs["reasoning"] is True
            return LMStudioChatResult(content="Use the planning notes.", reasoning="I checked context.")

    result = SearchResult(
        id="chunk_1",
        path="/docs/holiday.md",
        file_name="holiday.md",
        title="holiday",
        text="Holiday planning notes",
        snippet="Holiday planning notes",
        score=0.9,
        chunk_index=0,
    )

    answer = LMStudioLLMProvider(ThinkingClient(), "qwen").answer(
        "What did I write?",
        [result],
        reasoning=True,
    )

    assert "## Thinking" in answer
    assert "I checked context." in answer
    assert "Use the planning notes." in answer


def test_lmstudio_stream_answer_streams_only_answer_content():
    class StreamingClient:
        def native_chat_stream(self, *args, **kwargs):
            assert kwargs["previous_response_id"] is None
            assert kwargs["store"] is False
            yield LMStudioStreamDelta(content="Use")
            yield LMStudioStreamDelta(content=" notes")

    result = SearchResult(
        id="chunk_1",
        path="/docs/holiday.md",
        file_name="holiday.md",
        title="holiday",
        text="Holiday planning notes",
        snippet="Holiday planning notes",
        score=0.9,
        chunk_index=0,
    )

    chunks = list(LMStudioLLMProvider(StreamingClient(), "qwen").stream_answer("Q?", [result]))

    assert chunks[0] == "Use"
    assert chunks[1] == " notes"
    assert "Sources" not in "".join(chunks)


def test_lmstudio_stream_answer_disables_reasoning_by_default():
    class ThinkingStreamingClient:
        def native_chat_stream(self, *args, **kwargs):
            assert kwargs["reasoning"] is False
            yield LMStudioStreamDelta(reasoning="checking")
            yield LMStudioStreamDelta(reasoning=" sources")
            yield LMStudioStreamDelta(content="Use")
            yield LMStudioStreamDelta(content=" notes")

    result = SearchResult(
        id="chunk_1",
        path="/docs/holiday.md",
        file_name="holiday.md",
        title="holiday",
        text="Holiday planning notes",
        snippet="Holiday planning notes",
        score=0.9,
        chunk_index=0,
    )

    chunks = list(LMStudioLLMProvider(ThinkingStreamingClient(), "qwen").stream_answer("Q?", [result]))

    assert chunks == ["Use", " notes"]


def test_lmstudio_stream_answer_enables_reasoning_when_requested():
    class ThinkingStreamingClient:
        def native_chat_stream(self, *args, **kwargs):
            yield LMStudioStreamDelta(reasoning="checking")
            yield LMStudioStreamDelta(content="Use notes")

    result = SearchResult(
        id="chunk_1",
        path="/docs/holiday.md",
        file_name="holiday.md",
        title="holiday",
        text="Holiday planning notes",
        snippet="Holiday planning notes",
        score=0.9,
        chunk_index=0,
    )

    output = "".join(
        LMStudioLLMProvider(ThinkingStreamingClient(), "qwen").stream_answer(
            "Q?", [result], reasoning=True
        )
    )

    assert "## Thinking" in output
    assert "checking" in output
    assert "## Answer" in output
    assert "Use notes" in output


def test_lmstudio_stream_answer_falls_back_when_model_returns_no_content():
    class EmptyStreamingClient:
        def native_chat_stream(self, *args, **kwargs):
            yield LMStudioStreamDelta(reasoning="checking")

    result = SearchResult(
        id="chunk_1",
        path="/docs/scanned.pdf",
        file_name="scanned.pdf",
        title="scanned",
        text="Missouri public water systems laboratory notice.",
        snippet="Missouri public water systems laboratory notice.",
        score=0.9,
        chunk_index=0,
    )

    chunks = list(LMStudioLLMProvider(EmptyStreamingClient(), "qwen").stream_answer("Q?", [result]))
    output = "".join(chunks)

    assert "model did not return visible answer text" in output
    assert "Missouri public water systems" in output
    assert "checking" not in output
    assert "Sources" not in output


def test_lmstudio_answer_falls_back_when_model_returns_empty_content():
    class EmptyClient:
        def native_chat(self, *args, **kwargs):
            return LMStudioChatResult(content="")

    result = SearchResult(
        id="chunk_1",
        path="/docs/scanned.pdf",
        file_name="scanned.pdf",
        title="scanned",
        text="Missouri public water systems laboratory notice.",
        snippet="Missouri public water systems laboratory notice.",
        score=0.9,
        chunk_index=0,
    )

    answer = LMStudioLLMProvider(EmptyClient(), "qwen").answer("Q?", [result])

    assert "model did not return visible answer text" in answer
    assert "Missouri public water systems" in answer
    assert "Sources" not in answer


def test_lmstudio_provider_continues_stateful_session_with_response_id():
    calls = []

    class StatefulClient:
        def native_chat(self, *args, **kwargs):
            calls.append((args, kwargs))
            response_number = len(calls)
            return LMStudioChatResult(
                content=f"Answer {response_number}",
                response_id=f"resp_{response_number}",
            )

    provider = LMStudioLLMProvider(StatefulClient(), "qwen")
    session = ChatSession()
    result = SearchResult(
        id="chunk_1",
        path="/docs/holiday.md",
        file_name="holiday.md",
        title="holiday",
        text="Holiday planning notes",
        snippet="Holiday planning notes",
        score=0.9,
        chunk_index=0,
    )
    second_result = SearchResult(
        id="chunk_2",
        path="/docs/invoice.pdf",
        file_name="invoice.pdf",
        title="invoice",
        text="The invoice total is $125.",
        snippet="The invoice total is $125.",
        score=0.95,
        chunk_index=0,
    )

    provider.answer("Tell me about it", [result], session=session)
    provider.answer("What is the invoice total?", [second_result], session=session)

    assert calls[0][0][2] == provider._system_prompt()
    assert calls[0][1]["previous_response_id"] is None
    assert calls[0][1]["store"] is True
    assert calls[1][0][2] is None
    assert calls[1][1]["previous_response_id"] == "resp_1"
    assert "Tell me about it" not in calls[1][0][1]
    assert "Answer 1" not in calls[1][0][1]
    assert "The invoice total is $125." in calls[1][0][1]
    assert "Holiday planning notes" not in calls[1][0][1]
    assert session.provider_state["response_id"] == "resp_2"


def test_lmstudio_native_prompt_frames_context_without_requesting_sources():
    provider = LMStudioLLMProvider(LMStudioClient(), "qwen")
    result = SearchResult(
        id="chunk_1",
        path="/docs/paper.pdf",
        file_name="paper.pdf",
        title="paper",
        text="The paper discusses sycophancy in large language models.",
        snippet="The paper discusses sycophancy in large language models.",
        score=0.87,
        chunk_index=2,
    )

    system = provider._system_prompt()
    user = provider._input("What is this paper about?", [result])

    assert "GitHub-flavored Markdown" in system
    assert "Do not include a Sources section" in system
    assert "OpenMind returns sources separately" in system
    assert "Retrieved local file evidence for this turn" in user
    assert "Path: /docs/paper.pdf" in user
    assert "Retrieval score: 0.87" in user
    assert "Do not add sources or citations" in user


def test_context_only_answer_still_available_for_dev_fallback():
    assert "did not find" in ContextOnlyAnswerProvider().answer("anything?", [])
