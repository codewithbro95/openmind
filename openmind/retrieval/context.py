from __future__ import annotations

from openmind.core.models import SearchResult


def build_context(results: list[SearchResult], max_chars: int = 10000) -> str:
    parts: list[str] = []
    used = 0
    for index, result in enumerate(results, start=1):
        header = (
            f"[Source {index}]\n"
            f"Path: {result.path}\n"
            f"Chunk: {result.chunk_index}\n"
            f"Retrieval score: {result.score:.2f}"
        )
        body = result.text.strip()
        block = f"{header}\n{body}"
        if used + len(block) > max_chars:
            remaining = max_chars - used
            if remaining <= len(header) + 20:
                break
            block = block[:remaining]
        parts.append(block)
        used += len(block)
        if used >= max_chars:
            break
    return "\n\n".join(parts)


def format_sources(results: list[SearchResult]) -> list[str]:
    seen: set[str] = set()
    sources: list[str] = []
    for result in results:
        if result.path in seen:
            continue
        seen.add(result.path)
        sources.append(result.path)
    return sources
