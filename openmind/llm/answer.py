from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator

from openmind.core.models import SearchResult
from openmind.retrieval.context import build_context, format_sources


class AnswerProvider(ABC):
    @abstractmethod
    def answer(
        self,
        question: str,
        context: list[SearchResult],
        show_thinking: bool = False,
        history: list[dict[str, str]] | None = None,
    ) -> str:
        raise NotImplementedError

    def stream_answer(
        self,
        question: str,
        context: list[SearchResult],
        show_thinking: bool = False,
        history: list[dict[str, str]] | None = None,
    ) -> Iterator[str]:
        yield self.answer(
            question,
            context,
            show_thinking=show_thinking,
            history=history,
        )


class ContextOnlyAnswerProvider(AnswerProvider):
    def answer(
        self,
        question: str,
        context: list[SearchResult],
        show_thinking: bool = False,
        history: list[dict[str, str]] | None = None,
    ) -> str:
        if not context:
            return "I did not find any indexed documents that match this question."

        sources = format_sources(context)
        lines = [
            "No LLM provider is configured, so I am returning the strongest retrieved context.",
            "",
            f"Question: {question}",
            "",
            "Top matches:",
        ]
        for index, result in enumerate(context, start=1):
            lines.append(f"{index}. {result.path}")
            lines.append(f"   Score: {result.score:.2f}")
            lines.append(f"   Snippet: {result.snippet}")
        lines.extend(["", "Sources:"])
        lines.extend(f"- {source}" for source in sources)
        lines.extend(["", "Retrieved context:", build_context(context, max_chars=6000)])
        return "\n".join(lines).strip()
