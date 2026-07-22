from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from openmind.api.deps import EngineDependency
from openmind.api.schemas import WatchStatusResponse
from openmind.watcher.errors import WatchError
from openmind.watcher.state import WatchStatus

router = APIRouter(prefix="/watch", tags=["watch"])


@router.post("/start", response_model=WatchStatusResponse, status_code=status.HTTP_202_ACCEPTED)
def start_watch(engine: EngineDependency) -> WatchStatusResponse:
    try:
        return _response(engine.start_watch())
    except WatchError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/status", response_model=WatchStatusResponse)
def watch_status(engine: EngineDependency) -> WatchStatusResponse:
    return _response(engine.watch_status())


@router.post("/stop", response_model=WatchStatusResponse)
def stop_watch(engine: EngineDependency) -> WatchStatusResponse:
    return _response(engine.stop_watch())


def _response(current: WatchStatus) -> WatchStatusResponse:
    return WatchStatusResponse(
        state=current.state,
        sources=current.sources,
        queued_jobs=current.queued_jobs,
        current_file=current.current_file,
        last_event_at=current.last_event_at,
        last_indexed_at=current.last_indexed_at,
        errors=current.errors,
    )
