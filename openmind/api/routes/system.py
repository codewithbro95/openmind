from __future__ import annotations

from fastapi import APIRouter

from openmind import __version__
from openmind.api.deps import EngineDependency
from openmind.api.schemas import (
    HealthResponse,
    ProviderInfo,
    ProvidersResponse,
    ProviderStatusResponse,
    StatusResponse,
)

public_router = APIRouter(tags=["system"])
router = APIRouter(tags=["system"])


@public_router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", version=__version__)


@router.get("/status", response_model=StatusResponse)
def status(engine: EngineDependency) -> StatusResponse:
    summary = engine.status()
    job = engine.index_job_status()
    active_states = {"pending", "discovering", "running", "pause_requested", "paused"}
    indexing_state = job.status if job and job.status in active_states else "idle"
    image_model = (
        engine.config.extraction.images.model if engine.config.extraction.images.enabled else None
    )
    return StatusResponse(
        status="ready",
        version=__version__,
        provider=engine.config.provider.name,
        chat_model=engine.config.models.chat_model or None,
        embedding_model=engine.config.models.embedding_model or None,
        image_model=image_model,
        sources=summary.sources,
        indexed_files=summary.indexed_files,
        indexed_chunks=engine.lance.count_chunks(),
        indexing_state=indexing_state,
        last_index_job_status=job.status if job else None,
    )


@router.get("/providers/status", response_model=ProviderStatusResponse)
def provider_status(engine: EngineDependency) -> ProviderStatusResponse:
    reachable, message = engine.provider_status()
    return ProviderStatusResponse(
        provider=engine.config.provider.name,
        reachable=reachable,
        message=message,
    )


@router.get("/providers", response_model=ProvidersResponse)
def providers(engine: EngineDependency) -> ProvidersResponse:
    return ProvidersResponse(
        providers=[
            ProviderInfo(
                name="lmstudio",
                display_name="LM Studio",
                configured=engine.config.provider.name == "lmstudio",
            )
        ]
    )
