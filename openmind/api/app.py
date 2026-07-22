from __future__ import annotations

from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from openmind import __version__
from openmind.api.auth import ensure_api_token, require_api_token
from openmind.api.cors import validate_cors_origin
from openmind.api.files import open_local_file
from openmind.api.routes import (
    actions,
    ignore_rules,
    indexing,
    memory,
    models,
    sources,
    system,
    watching,
)
from openmind.core.engine import OpenMindEngine
from openmind.providers.lmstudio.errors import LMStudioError

API_PREFIX = "/api/v1"


def create_app(
    engine: OpenMindEngine | None = None,
    api_token: str | None = None,
    allowed_origins: list[str] | None = None,
    file_opener: Callable[[Path], None] | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        current = engine or OpenMindEngine()
        current.init()
        app.state.engine = current
        if api_token is None:
            app.state.api_token_loader = lambda: ensure_api_token(current.paths.home)
        else:
            app.state.api_token_loader = lambda: api_token
        app.state.file_opener = file_opener or open_local_file
        yield

    app = FastAPI(
        title="OpenMind Core API",
        version=__version__,
        description="Local, authenticated API for OpenMind client applications.",
        lifespan=lifespan,
    )
    origins = [validate_cors_origin(origin) for origin in (allowed_origins or [])]
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "PUT", "DELETE"],
            allow_headers=["Authorization", "Content-Type"],
        )

    protected = [Depends(require_api_token)]
    app.include_router(system.public_router)
    app.include_router(system.router, prefix=API_PREFIX, dependencies=protected)
    app.include_router(models.router, prefix=API_PREFIX, dependencies=protected)
    app.include_router(sources.router, prefix=API_PREFIX, dependencies=protected)
    app.include_router(ignore_rules.router, prefix=API_PREFIX, dependencies=protected)
    app.include_router(indexing.router, prefix=API_PREFIX, dependencies=protected)
    app.include_router(watching.router, prefix=API_PREFIX, dependencies=protected)
    app.include_router(memory.router, prefix=API_PREFIX, dependencies=protected)
    app.include_router(actions.router, prefix=API_PREFIX, dependencies=protected)

    @app.exception_handler(LMStudioError)
    async def provider_error(request: Request, exc: LMStudioError) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    return app
