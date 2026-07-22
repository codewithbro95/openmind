from __future__ import annotations

from pydantic import BaseModel, Field


class WatchState(BaseModel):
    id: str = "watcher"
    status: str = "stopped"
    started_at: str | None = None
    stopped_at: str | None = None
    updated_at: str | None = None
    pid: int | None = None
    error: str | None = None
    current_file: str | None = None
    last_event_at: str | None = None
    last_indexed_at: str | None = None
    sources: list[str] = Field(default_factory=list)


class WatchJob(BaseModel):
    id: str
    job_type: str
    path: str
    source_id: str
    status: str = "pending"
    priority: int = 0
    attempts: int = 0
    error: str | None = None
    created_at: str
    updated_at: str
    started_at: str | None = None
    completed_at: str | None = None


class WatchStatus(BaseModel):
    state: str
    sources: list[str] = Field(default_factory=list)
    queued_jobs: int = 0
    current_file: str | None = None
    last_event_at: str | None = None
    last_indexed_at: str | None = None
    errors: list[str] = Field(default_factory=list)
    pid: int | None = None
