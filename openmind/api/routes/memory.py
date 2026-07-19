from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, status
from fastapi.responses import StreamingResponse

from openmind.api.deps import EngineDependency
from openmind.api.schemas import (
    AskRequest,
    AskResponse,
    DocumentChunkResponse,
    DocumentResponse,
    SearchRequest,
    SearchResponse,
    SearchResultResponse,
)
from openmind.core.models import SearchResult

router = APIRouter(tags=["memory"])


@router.post("/search", response_model=SearchResponse)
def search(request: SearchRequest, engine: EngineDependency) -> SearchResponse:
    results = engine.search(request.query, limit=request.limit)
    return SearchResponse(
        query=request.query,
        results=[_search_result(result) for result in results],
    )


@router.post("/ask", response_model=AskResponse)
def ask(request: AskRequest, engine: EngineDependency) -> AskResponse:
    answer, results = engine.ask_with_sources(request.question, limit=request.limit)
    sources = [_search_result(result) for result in results] if request.include_sources else []
    return AskResponse(answer=answer, sources=sources)


@router.post("/ask/stream")
def ask_stream(request: AskRequest, engine: EngineDependency) -> StreamingResponse:
    stream, results = engine.ask_stream_with_sources(request.question, limit=request.limit)

    def events() -> Iterator[str]:
        try:
            for chunk in stream:
                yield _sse("delta", {"text": chunk})
            if request.include_sources:
                yield _sse(
                    "sources",
                    {
                        "sources": [
                            _search_result(result).model_dump(mode="json") for result in results
                        ]
                    },
                )
            yield _sse("done", {})
        except Exception:
            yield _sse("error", {"message": "OpenMind could not complete the answer."})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/documents/{file_id}", response_model=DocumentResponse)
def document(
    file_id: Annotated[str, Path(pattern=r"^file_[0-9a-f]{16}$")],
    engine: EngineDependency,
) -> DocumentResponse:
    record = engine.sqlite.file_by_id(file_id)
    if record is None or record.status != "indexed":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    chunks = engine.lance.chunks_for_file(file_id)
    return DocumentResponse(
        id=record.id,
        source_id=record.source_id,
        path=record.path,
        file_name=record.name,
        extension=record.extension,
        status=record.status,
        size=record.size,
        modified_at=record.modified_at,
        indexed_at=record.indexed_at,
        error=record.error,
        chunks=[DocumentChunkResponse(**chunk) for chunk in chunks],
    )


def _search_result(result: SearchResult) -> SearchResultResponse:
    return SearchResultResponse(
        id=result.id,
        file_id=result.file_id,
        source_id=result.source_id,
        score=result.score,
        source_type=result.extension.lstrip(".") or _source_type(result),
        path=result.path,
        file_name=result.file_name,
        title=result.title,
        snippet=result.snippet,
        chunk_index=result.chunk_index,
        metadata=result.metadata,
    )


def _source_type(result: SearchResult) -> str:
    suffix = result.metadata.get("extension") or ""
    if not suffix:
        suffix = "." + result.file_name.rsplit(".", 1)[-1] if "." in result.file_name else "file"
    return str(suffix).lstrip(".") or "file"


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=True)}\n\n"
