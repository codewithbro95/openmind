from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class LMStudioLoadedInstance(BaseModel):
    id: str
    config: dict[str, Any] = Field(default_factory=dict)


class LMStudioModel(BaseModel):
    type: str
    key: str
    display_name: str
    publisher: str | None = None
    loaded_instances: list[LMStudioLoadedInstance] = Field(default_factory=list)
    max_context_length: int | None = None
    quantization: dict[str, Any] | None = None
    capabilities: dict[str, Any] = Field(default_factory=dict)

    @property
    def is_loaded(self) -> bool:
        return bool(self.loaded_instances)

    @property
    def supports_images(self) -> bool:
        values: list[str] = [self.key, self.display_name, self.type]
        for key, value in self.capabilities.items():
            if value is True:
                values.append(str(key))
            elif isinstance(value, str):
                values.append(value)
            elif isinstance(value, list):
                values.extend(str(item) for item in value)
            elif isinstance(value, dict):
                values.extend(str(inner_key) for inner_key in value)
                values.extend(str(inner_value) for inner_value in value.values())
        haystack = " ".join(values).lower()
        return any(
            token in haystack
            for token in ("vision", "image", "multimodal", "vlm", "smolvlm", "llava")
        )


def split_models(models: list[LMStudioModel]) -> tuple[list[LMStudioModel], list[LMStudioModel]]:
    chat_models = [model for model in models if model.type == "llm"]
    embedding_models = [model for model in models if model.type == "embedding"]
    return chat_models, embedding_models


def vision_models(models: list[LMStudioModel]) -> list[LMStudioModel]:
    return [model for model in models if model.type == "llm" and model.supports_images]
