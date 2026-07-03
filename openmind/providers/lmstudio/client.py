from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from openmind.providers.lmstudio.errors import LMStudioConnectionError, LMStudioModelError
from openmind.providers.lmstudio.models import LMStudioModel


class LMStudioClient:
    def __init__(
        self,
        base_url: str = "http://localhost:1234",
        api_token: str | None = None,
        timeout: float = 10.0,
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

    def is_model_loaded(self, model_key: str) -> bool:
        for model in self.list_models():
            if model.key == model_key:
                return model.is_loaded
        raise LMStudioModelError(f"Selected model is not available in LM Studio: {model_key}")

    def chat(self, model: str, messages: list[dict[str, str]]) -> str:
        data = self._request(
            "POST",
            "/v1/chat/completions",
            {
                "model": model,
                "messages": messages,
                "temperature": 0.2,
            },
        )
        choices = data.get("choices") or []
        if not choices:
            raise LMStudioModelError("LM Studio returned no chat choices.")
        message = choices[0].get("message") or {}
        return str(message.get("content") or "").strip()

    def embed(self, model: str, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        data = self._request("POST", "/v1/embeddings", {"model": model, "input": texts})
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
        except urllib.error.URLError as exc:
            raise LMStudioConnectionError(
                f"LM Studio is not reachable at {self.base_url}. "
                "Start it from the LM Studio Developer tab or run: lms server start"
            ) from exc
        except TimeoutError as exc:
            raise LMStudioConnectionError(f"Timed out connecting to LM Studio at {self.base_url}") from exc

        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LMStudioModelError("LM Studio returned invalid JSON.") from exc
