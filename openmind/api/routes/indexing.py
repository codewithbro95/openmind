from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from openmind.api.deps import EngineDependency
from openmind.api.schemas import IndexJobResponse
from openmind.core.models import IndexJob

router = APIRouter(prefix="/index", tags=["indexing"])


@router.post("/start", response_model=IndexJobResponse, status_code=status.HTTP_202_ACCEPTED)
def start_index(engine: EngineDependency) -> IndexJobResponse:
    return _job_response(engine.start_index_job())


@router.get("/status", response_model=IndexJobResponse)
def index_status(engine: EngineDependency) -> IndexJobResponse:
    job = engine.index_job_status()
    return _job_response(job)


@router.post("/pause", response_model=IndexJobResponse)
def pause_index(engine: EngineDependency) -> IndexJobResponse:
    return _required_job(engine.pause_index_job())


@router.post("/resume", response_model=IndexJobResponse)
def resume_index(engine: EngineDependency) -> IndexJobResponse:
    return _required_job(engine.resume_index_job())


@router.post("/stop", response_model=IndexJobResponse)
def stop_index(engine: EngineDependency) -> IndexJobResponse:
    return _required_job(engine.stop_index_job())


def _required_job(job: IndexJob | None) -> IndexJobResponse:
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No indexing job has been started.",
        )
    return _job_response(job)


def _job_response(job: IndexJob | None) -> IndexJobResponse:
    if job is None:
        return IndexJobResponse(
            job_id=None,
            state="idle",
            total_files=0,
            processed_files=0,
            indexed_files=0,
            skipped_files=0,
            already_indexed_files=0,
            failed_files=0,
            chunks_created=0,
            current_file=None,
            error=None,
            progress=0.0,
            started_at=None,
            completed_at=None,
            updated_at=None,
        )
    return IndexJobResponse(
        job_id=job.id,
        state=job.status,
        total_files=job.total_files,
        processed_files=job.processed_files,
        indexed_files=job.indexed_files,
        skipped_files=job.skipped_files,
        already_indexed_files=job.already_indexed_files,
        failed_files=job.failed_files,
        chunks_created=job.total_chunks,
        current_file=job.current_file,
        error=job.error,
        progress=job.progress_percent,
        started_at=job.started_at,
        completed_at=job.completed_at,
        updated_at=job.updated_at,
    )
