from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class LMStudioLoadedInstance(BaseModel):
    id: str
    config: dict[str, Any] = Field(default_factory=dict)


class LMStudioModel(BaseModel):
    type: Literal["llm", "embedding"]
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


def split_models(models: list[LMStudioModel]) -> tuple[list[LMStudioModel], list[LMStudioModel]]:
    chat_models = [model for model in models if model.type == "llm"]
    embedding_models = [model for model in models if model.type == "embedding"]
    return chat_models, embedding_models
