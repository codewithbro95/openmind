from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from openmind.api.deps import EngineDependency
from openmind.api.schemas import (
    ModelInfo,
    ModelLoadRequest,
    ModelLoadResponse,
    ModelLoadResult,
    ModelSelectionRequest,
    ModelSelectionResponse,
    ModelsResponse,
)
from openmind.providers.lmstudio.models import LMStudioModel, split_models, vision_models

router = APIRouter(prefix="/models", tags=["models"])


@router.get("", response_model=ModelsResponse)
def list_models(engine: EngineDependency) -> ModelsResponse:
    models = engine.list_lmstudio_models()
    chat_models, embedding_models = split_models(models)
    image_models = vision_models(models)
    return ModelsResponse(
        provider="lmstudio",
        chat_models=[_model_info(model) for model in chat_models],
        embedding_models=[_model_info(model) for model in embedding_models],
        image_models=[_model_info(model) for model in image_models],
    )


@router.post("/load", response_model=ModelLoadResponse)
def load_models(request: ModelLoadRequest, engine: EngineDependency) -> ModelLoadResponse:
    if request.model_keys is None:
        results = engine.load_configured_models()
    else:
        available = {model.key for model in engine.list_lmstudio_models()}
        unknown = [key for key in request.model_keys if key not in available]
        if unknown:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown model key(s): {', '.join(unknown)}",
            )
        client = engine.lmstudio_client()
        results = [client.load_model_if_needed(key) for key in request.model_keys]
    return ModelLoadResponse(results=[_load_result(result) for result in results])


@router.put("/selection", response_model=ModelSelectionResponse)
def select_models(
    request: ModelSelectionRequest,
    engine: EngineDependency,
) -> ModelSelectionResponse:
    models = engine.list_lmstudio_models()
    by_key = {model.key: model for model in models}
    _require_model_type(by_key, request.embedding_model, "embedding")
    if request.chat_model:
        _require_model_type(by_key, request.chat_model, "llm")
    if request.image_model:
        model = _require_model_type(by_key, request.image_model, "llm")
        if not model.supports_images:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Model does not advertise image support: {request.image_model}",
            )

    config = engine.config.model_copy(deep=True)
    config.provider.name = "lmstudio"
    config.models.chat_model = request.chat_model or ""
    config.models.embedding_model = request.embedding_model
    config.extraction.images.enabled = request.image_model is not None
    if request.image_model:
        config.extraction.images.model = request.image_model
    transition = engine.update_model_config(config, load=request.load)
    return ModelSelectionResponse(
        provider="lmstudio",
        chat_model=request.chat_model,
        embedding_model=request.embedding_model,
        image_model=request.image_model,
        unload_results=[_load_result(result) for result in transition.unload_results],
        load_results=[_load_result(result) for result in transition.load_results],
    )


def _model_info(model: LMStudioModel) -> ModelInfo:
    return ModelInfo(
        key=model.key,
        name=model.display_name,
        type=model.type,
        loaded=model.is_loaded,
        supports_images=model.supports_images,
        max_context_length=model.max_context_length,
        quantization=model.quantization,
    )


def _load_result(result: dict) -> ModelLoadResult:
    return ModelLoadResult(
        model=str(result.get("model", "")),
        status=str(result.get("status", "loaded")),
        skipped=bool(result.get("skipped", False)),
    )


def _require_model_type(
    models: dict[str, LMStudioModel],
    model_key: str,
    expected_type: str,
) -> LMStudioModel:
    model = models.get(model_key)
    if model is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown model key: {model_key}",
        )
    if model.type != expected_type:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Model {model_key} is not a {expected_type} model.",
        )
    return model
