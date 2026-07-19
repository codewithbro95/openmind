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
    ChatSessionResponse,
    DocumentChunkResponse,
    DocumentResponse,
    SearchRequest,
    SearchResponse,
    SearchResultResponse,
)
from openmind.core.engine import OpenMindEngine
from openmind.core.models import SearchResult
from openmind.llm.session import ChatSession

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
    session = _chat_session(engine, request.session_id)
    answer, results = engine.ask_with_sources(
        request.question,
        limit=request.limit,
        reasoning=request.reasoning,
        session=session,
    )
    sources = [_search_result(result) for result in results] if request.include_sources else []
    return AskResponse(session_id=session.id, answer=answer, sources=sources)


@router.post("/ask/stream")
def ask_stream(request: AskRequest, engine: EngineDependency) -> StreamingResponse:
    session = _chat_session(engine, request.session_id)
    stream, results = engine.ask_stream_with_sources(
        request.question,
        limit=request.limit,
        reasoning=request.reasoning,
        session=session,
    )

    def events() -> Iterator[str]:
        try:
            yield _sse(
                "meta",
                {
                    "format": "markdown",
                    "session_id": session.id,
                    "reasoning": request.reasoning,
                },
            )
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
            yield _sse("done", {"session_id": session.id})
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


@router.delete("/chat/sessions/{session_id}", response_model=ChatSessionResponse)
def end_chat_session(
    session_id: Annotated[str, Path(pattern=r"^chat_[0-9a-f]{16}$")],
    engine: EngineDependency,
) -> ChatSessionResponse:
    if not engine.end_chat_session(session_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat session not found.")
    return ChatSessionResponse(session_id=session_id, ended=True)


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


def _chat_session(engine: OpenMindEngine, session_id: str | None) -> ChatSession:
    if session_id is None:
        return engine.create_chat_session()
    session = engine.chat_session(session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat session not found.")
    return session


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=True)}\n\n"
