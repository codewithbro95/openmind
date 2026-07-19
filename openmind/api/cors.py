from __future__ import annotations

from urllib.parse import urlsplit


def validate_cors_origin(origin: str) -> str:
    value = origin.strip().rstrip("/")
    parsed = urlsplit(value)
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError("CORS origins must use a valid port.") from exc
    if (
        value == "*"
        or parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or "*" in parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "CORS origins must be exact http(s) origins such as http://localhost:3000."
        )
    return value
