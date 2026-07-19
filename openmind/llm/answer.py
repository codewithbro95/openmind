from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator

from openmind.core.models import SearchResult
from openmind.llm.session import ChatSession


class AnswerProvider(ABC):
    @abstractmethod
    def answer(
        self,
        question: str,
        context: list[SearchResult],
        reasoning: bool = False,
        history: list[dict[str, str]] | None = None,
        session: ChatSession | None = None,
    ) -> str:
        raise NotImplementedError

    def stream_answer(
        self,
        question: str,
        context: list[SearchResult],
        reasoning: bool = False,
        history: list[dict[str, str]] | None = None,
        session: ChatSession | None = None,
    ) -> Iterator[str]:
        yield self.answer(
            question,
            context,
            reasoning=reasoning,
            history=history,
            session=session,
        )


class ContextOnlyAnswerProvider(AnswerProvider):
    def answer(
        self,
        question: str,
        context: list[SearchResult],
        reasoning: bool = False,
        history: list[dict[str, str]] | None = None,
        session: ChatSession | None = None,
    ) -> str:
        if not context:
            return "I did not find any indexed documents that match this question."

        lines = [
            "No LLM provider is configured, so I am returning the strongest retrieved context.",
            "",
            f"**Question:** {question}",
            "",
            "## Retrieved context",
        ]
        for index, result in enumerate(context, start=1):
            lines.append(f"{index}. {result.snippet}")
        return "\n".join(lines).strip()
