from __future__ import annotations

import json
import os
import re
import socket
import urllib.error
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from openmind.providers.lmstudio.errors import LMStudioConnectionError, LMStudioModelError
from openmind.providers.lmstudio.models import LMStudioModel

DEFAULT_CHAT_MAX_TOKENS = 700


@dataclass(frozen=True)
class LMStudioChatResult:
    content: str
    reasoning: str = ""


@dataclass(frozen=True)
class LMStudioStreamDelta:
    content: str = ""
    reasoning: str = ""


class LMStudioClient:
    def __init__(
        self,
        base_url: str = "http://localhost:1234",
        api_token: str | None = None,
        timeout: float = 120.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token or os.environ.get("LM_API_TOKEN")
        self.timeout = timeout

    @property
    def openai_base_url(self) -> str:
        return f"{self.base_url}/v1"

    def health_check(self) -> bool:
        try:
            self.list_models()
            return True
        except LMStudioConnectionError:
            return False

    def list_models(self) -> list[LMStudioModel]:
        data = self._request("GET", "/api/v1/models")
        return [LMStudioModel(**item) for item in data.get("models", [])]

    def load_model(self, model_key: str, context_length: int | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"model": model_key}
        if context_length is not None:
            payload["context_length"] = context_length
        return self._request("POST", "/api/v1/models/load", payload)

    def load_model_if_needed(
        self,
        model_key: str,
        context_length: int | None = None,
    ) -> dict[str, Any]:
        if self.is_model_loaded(model_key):
            return {"status": "already_loaded", "model": model_key, "skipped": True}
        response = self.load_model(model_key, context_length=context_length)
        response.setdefault("model", model_key)
        response["skipped"] = False
        return response

    def is_model_loaded(self, model_key: str) -> bool:
        for model in self.list_models():
            if model.key == model_key:
                return model.is_loaded
        raise LMStudioModelError(f"Selected model is not available in LM Studio: {model_key}")

    def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        max_tokens: int = DEFAULT_CHAT_MAX_TOKENS,
    ) -> LMStudioChatResult:
        data = self._request(
            "POST",
            "/v1/chat/completions",
            {
                "model": model,
                "messages": messages,
                "temperature": 0.2,
                "max_tokens": max_tokens,
            },
        )
        choices = data.get("choices") or []
        if not choices:
            raise LMStudioModelError("LM Studio returned no chat choices.")
        message = choices[0].get("message") or {}
        content = str(message.get("content") or "").strip()
        reasoning = _extract_reasoning_from_mapping(message)
        parsed_reasoning, parsed_content = _extract_think_block(content)
        return LMStudioChatResult(
            content=parsed_content.strip(),
            reasoning=(reasoning or parsed_reasoning).strip(),
        )

    def chat_stream(
        self,
        model: str,
        messages: list[dict[str, str]],
    ) -> Iterator[LMStudioStreamDelta]:
        for event in self._stream_request(
            "POST",
            "/v1/chat/completions",
            {
                "model": model,
                "messages": messages,
                "temperature": 0.2,
                "max_tokens": DEFAULT_CHAT_MAX_TOKENS,
                "stream": True,
            },
        ):
            choices = event.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            content = str(delta.get("content") or "")
            reasoning = _extract_reasoning_from_mapping(delta)
            if content or reasoning:
                yield LMStudioStreamDelta(content=content, reasoning=reasoning)

    def respond_with_reasoning(
        self,
        model: str,
        messages: list[dict[str, str]],
        effort: str = "medium",
    ) -> LMStudioChatResult:
        data = self._request(
            "POST",
            "/v1/responses",
            {
                "model": model,
                "input": messages,
                "reasoning": {"effort": effort},
                "max_output_tokens": DEFAULT_CHAT_MAX_TOKENS,
            },
        )
        return _parse_response_result(data)

    def respond_stream(
        self,
        model: str,
        messages: list[dict[str, str]],
        effort: str = "medium",
    ) -> Iterator[LMStudioStreamDelta]:
        for event in self._stream_request(
            "POST",
            "/v1/responses",
            {
                "model": model,
                "input": messages,
                "reasoning": {"effort": effort},
                "max_output_tokens": DEFAULT_CHAT_MAX_TOKENS,
                "stream": True,
            },
        ):
            event_type = str(event.get("type") or "")
            delta = event.get("delta")
            if "reasoning" in event_type and isinstance(delta, str):
                yield LMStudioStreamDelta(reasoning=delta)
            elif "output_text.delta" in event_type and isinstance(delta, str):
                yield LMStudioStreamDelta(content=delta)
            else:
                extracted = _stream_delta_from_event(event)
                if extracted.content or extracted.reasoning:
                    yield extracted

    def embed(self, model: str, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        normalized_texts = [text.replace("\n", " ") for text in texts]
        data = self._request("POST", "/v1/embeddings", {"model": model, "input": normalized_texts})
        embeddings = []
        for item in data.get("data", []):
            embeddings.append([float(value) for value in item["embedding"]])
        if len(embeddings) != len(texts):
            raise LMStudioModelError("LM Studio returned an unexpected embedding count.")
        return embeddings

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}{path}"
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise LMStudioModelError(f"LM Studio API error {exc.code}: {detail}") from exc
        except (TimeoutError, socket.timeout) as exc:
            raise LMStudioConnectionError(
                f"Timed out waiting for LM Studio at {self.base_url}. "
                "If the model is still loading, wait a moment and retry. "
                "You can also run: openmind models load"
            ) from exc
        except urllib.error.URLError as exc:
            raise LMStudioConnectionError(
                f"LM Studio is not reachable at {self.base_url}. "
                "Start it from the LM Studio Developer tab or run: lms server start"
            ) from exc

        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LMStudioModelError("LM Studio returned invalid JSON.") from exc

    def _stream_request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any],
    ) -> Iterator[dict[str, Any]]:
        url = f"{self.base_url}{path}"
        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data_lines: list[str] = []
                for raw_line in response:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line:
                        yield from _decode_sse_data_lines(data_lines)
                        data_lines = []
                        continue
                    if line.startswith(":"):
                        continue
                    if line.startswith("data:"):
                        data_lines.append(line.removeprefix("data:").strip())
                yield from _decode_sse_data_lines(data_lines)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise LMStudioModelError(f"LM Studio API error {exc.code}: {detail}") from exc
        except (TimeoutError, socket.timeout) as exc:
            raise LMStudioConnectionError(
                f"Timed out waiting for LM Studio at {self.base_url}. "
                "If the model is still loading, wait a moment and retry. "
                "You can also run: openmind models load"
            ) from exc
        except urllib.error.URLError as exc:
            raise LMStudioConnectionError(
                f"LM Studio is not reachable at {self.base_url}. "
                "Start it from the LM Studio Developer tab or run: lms server start"
            ) from exc


def _extract_reasoning_from_mapping(value: dict[str, Any]) -> str:
    candidates = [
        value.get("reasoning_content"),
        value.get("reasoning"),
        value.get("thinking"),
        value.get("thoughts"),
    ]
    for candidate in candidates:
        extracted = _stringify_reasoning(candidate)
        if extracted:
            return extracted
    return ""


def _stringify_reasoning(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts = [_stringify_reasoning(item) for item in value]
        return "\n".join(part for part in parts if part).strip()
    if isinstance(value, dict):
        for key in ("text", "content", "summary"):
            extracted = _stringify_reasoning(value.get(key))
            if extracted:
                return extracted
        return json.dumps(value, ensure_ascii=True)
    return str(value).strip()


def _extract_think_block(content: str) -> tuple[str, str]:
    match = re.search(r"<think>(.*?)</think>", content, flags=re.DOTALL | re.IGNORECASE)
    if not match:
        return "", content
    reasoning = match.group(1).strip()
    visible = (content[: match.start()] + content[match.end() :]).strip()
    return reasoning, visible


def _parse_response_result(data: dict[str, Any]) -> LMStudioChatResult:
    content_parts: list[str] = []
    reasoning_parts: list[str] = []

    output_text = data.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        content_parts.append(output_text.strip())

    reasoning = _extract_reasoning_from_mapping(data)
    if reasoning:
        reasoning_parts.append(reasoning)

    for item in data.get("output") or []:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or "")
        if "reasoning" in item_type:
            extracted = _extract_reasoning_from_mapping(item) or _stringify_reasoning(item)
            if extracted:
                reasoning_parts.append(extracted)
            continue
        for content_item in item.get("content") or []:
            if not isinstance(content_item, dict):
                continue
            text = content_item.get("text")
            if isinstance(text, str) and text.strip():
                content_parts.append(text.strip())
            extracted = _extract_reasoning_from_mapping(content_item)
            if extracted:
                reasoning_parts.append(extracted)

    content = "\n".join(dict.fromkeys(content_parts)).strip()
    think_reasoning, content_without_think = _extract_think_block(content)
    if think_reasoning:
        reasoning_parts.append(think_reasoning)
        content = content_without_think

    return LMStudioChatResult(
        content=content,
        reasoning="\n".join(dict.fromkeys(part for part in reasoning_parts if part)).strip(),
    )


def _decode_sse_data_lines(data_lines: list[str]) -> Iterator[dict[str, Any]]:
    if not data_lines:
        return
    payload = "\n".join(data_lines).strip()
    if not payload or payload == "[DONE]":
        return
    try:
        decoded = json.loads(payload)
    except json.JSONDecodeError:
        return
    if isinstance(decoded, dict):
        yield decoded


def _stream_delta_from_event(event: dict[str, Any]) -> LMStudioStreamDelta:
    content = ""
    reasoning = ""

    for key in ("output_text", "text", "content"):
        value = event.get(key)
        if isinstance(value, str):
            content += value

    extracted_reasoning = _extract_reasoning_from_mapping(event)
    if extracted_reasoning:
        reasoning += extracted_reasoning

    item = event.get("item")
    if isinstance(item, dict):
        if "reasoning" in str(item.get("type") or ""):
            reasoning += _extract_reasoning_from_mapping(item) or _stringify_reasoning(item)

    return LMStudioStreamDelta(content=content, reasoning=reasoning)
