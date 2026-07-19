from __future__ import annotations

import sqlite3

from fastapi import APIRouter, HTTPException, status

from openmind.api.deps import EngineDependency
from openmind.api.schemas import SourceCreateRequest, SourceListResponse, SourceResponse

router = APIRouter(prefix="/sources", tags=["sources"])


@router.get("", response_model=SourceListResponse)
def list_sources(engine: EngineDependency) -> SourceListResponse:
    return SourceListResponse(
        sources=[SourceResponse(**source.model_dump()) for source in engine.list_sources()]
    )


@router.post("", response_model=SourceResponse, status_code=status.HTTP_201_CREATED)
def add_source(request: SourceCreateRequest, engine: EngineDependency) -> SourceResponse:
    try:
        source = engine.add_source(request.path, recursive=request.recursive)
    except sqlite3.IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This source folder is already registered.",
        ) from exc
    except (FileNotFoundError, NotADirectoryError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return SourceResponse(**source.model_dump())


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_source(source_id: str, engine: EngineDependency) -> None:
    if not source_id.startswith("src_") or len(source_id) > 64:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found.")
    if not engine.remove_source(source_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found.")
