from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Annotated

from fastapi import HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

TOKEN_FILE_NAME = "api_token"
TOKEN_BYTES = 32

bearer_scheme = HTTPBearer(auto_error=False, scheme_name="OpenMind API token")


def token_path(home: Path) -> Path:
    return home / TOKEN_FILE_NAME


def ensure_api_token(home: Path) -> str:
    home.mkdir(parents=True, exist_ok=True)
    path = token_path(home)
    if path.exists():
        token = path.read_text(encoding="utf-8").strip()
        if len(token) < 32:
            raise RuntimeError(f"OpenMind API token is invalid: {path}")
        _secure_permissions(path)
        return token
    return _write_new_token(path)


def rotate_api_token(home: Path) -> str:
    home.mkdir(parents=True, exist_ok=True)
    path = token_path(home)
    token = secrets.token_urlsafe(TOKEN_BYTES)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(6)}.tmp")
    _write_private_file(temporary, token)
    temporary.replace(path)
    _secure_permissions(path)
    return token


def require_api_token(
    request: Request,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Security(bearer_scheme),
    ],
) -> None:
    expected = request.app.state.api_token_loader()
    supplied = credentials.credentials if credentials is not None else ""
    if not supplied or not secrets.compare_digest(supplied, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A valid OpenMind API bearer token is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _write_new_token(path: Path) -> str:
    token = secrets.token_urlsafe(TOKEN_BYTES)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return ensure_api_token(path.parent)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(token + "\n")
    _secure_permissions(path)
    return token


def _write_private_file(path: Path, token: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(token + "\n")


def _secure_permissions(path: Path) -> None:
    if os.name != "nt":
        path.chmod(0o600)
