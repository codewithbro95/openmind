from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from openmind.core.engine import OpenMindEngine


def get_engine(request: Request) -> OpenMindEngine:
    return request.app.state.engine


EngineDependency = Annotated[OpenMindEngine, Depends(get_engine)]
