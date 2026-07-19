from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, status

from openmind.api.deps import EngineDependency
from openmind.api.files import is_path_inside
from openmind.api.schemas import OpenFileRequest, OpenFileResponse

router = APIRouter(prefix="/actions", tags=["actions"])


@router.post("/open", response_model=OpenFileResponse)
def open_file(
    payload: OpenFileRequest,
    request: Request,
    engine: EngineDependency,
) -> OpenFileResponse:
    record = engine.sqlite.file_by_id(payload.file_id)
    if record is None or record.status != "indexed":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Indexed file not found.")

    resolved = Path(record.path).expanduser().resolve()
    if not resolved.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File no longer exists.")
    allowed = any(
        is_path_inside(resolved, Path(source.path).expanduser().resolve())
        for source in engine.list_sources()
        if source.enabled
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The file is outside enabled OpenMind sources.",
        )

    request.app.state.file_opener(resolved)
    return OpenFileResponse(opened=True, file_id=record.id, path=str(resolved))
