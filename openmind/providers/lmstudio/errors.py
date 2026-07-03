from __future__ import annotations


class LMStudioError(RuntimeError):
    pass


class LMStudioConnectionError(LMStudioError):
    pass


class LMStudioModelError(LMStudioError):
    pass
