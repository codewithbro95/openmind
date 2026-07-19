from __future__ import annotations

from collections.abc import Iterator

from openmind.core.models import SearchResult
from openmind.llm.answer import AnswerProvider
from openmind.llm.session import ChatSession
from openmind.providers.lmstudio.client import LMStudioClient
from openmind.providers.lmstudio.errors import LMStudioConnectionError, LMStudioModelError
from openmind.retrieval.context import build_context


class LMStudioLLMProvider(AnswerProvider):
    def __init__(self, client: LMStudioClient, model: str):
        self.client = client
        self.model = model

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

        try:
            previous_response_id = self._prepare_session(session)
            result = self.client.native_chat(
                self.model,
                self._input(question, context),
                self._system_prompt() if previous_response_id is None else None,
                previous_response_id=previous_response_id,
                store=session is not None,
                reasoning=reasoning,
            )
            self._update_session(session, result.response_id)
        except LMStudioConnectionError as exc:
            return str(exc)
        except LMStudioModelError as exc:
            return str(exc)

        sections: list[str] = []
        if reasoning and result.reasoning:
            sections.extend(["## Thinking", result.reasoning.strip(), "", "## Answer"])
        elif reasoning:
            sections.extend(
                [
                    "## Thinking",
                    "The selected model did not return explicit thinking/reasoning text.",
                    "",
                    "## Answer",
                ]
            )
        content = result.content.strip() or _empty_answer_fallback(context)
        sections.append(content)
        return "\n".join(sections).strip()

    def stream_answer(
        self,
        question: str,
        context: list[SearchResult],
        reasoning: bool = False,
        history: list[dict[str, str]] | None = None,
        session: ChatSession | None = None,
    ) -> Iterator[str]:
        if not context:
            yield "I did not find any indexed documents that match this question."
            return

        try:
            previous_response_id = self._prepare_session(session)
            stream = self.client.native_chat_stream(
                self.model,
                self._input(question, context),
                self._system_prompt() if previous_response_id is None else None,
                previous_response_id=previous_response_id,
                store=session is not None,
                reasoning=reasoning,
            )
            thinking_started = False
            answer_started = False
            thinking_seen = False
            content_seen = False

            for delta in stream:
                if delta.response_id:
                    self._update_session(session, delta.response_id)
                if reasoning and delta.reasoning:
                    if not thinking_started:
                        thinking_started = True
                        yield "## Thinking\n"
                    thinking_seen = True
                    yield delta.reasoning
                if delta.content:
                    if reasoning and not answer_started:
                        answer_started = True
                        if thinking_started:
                            yield "\n\n## Answer\n"
                        else:
                            yield "## Answer\n"
                    else:
                        answer_started = True
                    content_seen = True
                    yield delta.content

            if not content_seen:
                if reasoning and not thinking_seen:
                    yield (
                        "## Thinking\n"
                        "The selected model did not return explicit thinking/reasoning text.\n\n"
                        "## Answer\n"
                    )
                yield _empty_answer_fallback(context)
        except LMStudioConnectionError as exc:
            yield str(exc)
            return
        except LMStudioModelError as exc:
            yield str(exc)
            return

    def _prepare_session(self, session: ChatSession | None) -> str | None:
        if session is None:
            return None
        if session.provider_state.get("model") not in {None, self.model}:
            session.reset()
        return session.provider_state.get("response_id")

    def _update_session(self, session: ChatSession | None, response_id: str | None) -> None:
        if session is None or not response_id:
            return
        session.provider_state["model"] = self.model
        session.provider_state["response_id"] = response_id

    @staticmethod
    def _system_prompt() -> str:
        return (
            "You are OpenMind's local answer layer. Use the retrieved local file evidence in "
            "each message to answer the user's question. Use the existing conversation state "
            "to understand follow-up questions. If evidence is partial, answer only what it "
            "supports and say what was not found. Return concise GitHub-flavored Markdown. "
            "Format any non-source URL included in the answer as a Markdown link. "
            "Do not include a Sources section, citations, local file paths, or source links; "
            "OpenMind returns sources separately. Do not introduce yourself or name the model."
        )

    @staticmethod
    def _input(question: str, context: list[SearchResult]) -> str:
        return (
            f"Question:\n{question}\n\n"
            "Retrieved local file evidence for this turn:\n"
            f"{build_context(context)}\n\n"
            "Answer only the question from this evidence. Do not add sources or citations."
        )


def _empty_answer_fallback(context: list[SearchResult]) -> str:
    lines = [
        "The model did not return visible answer text, but OpenMind found relevant local context.",
        "",
        "### Top retrieved evidence",
    ]
    for index, result in enumerate(context[:3], start=1):
        lines.append(f"{index}. {result.snippet}")
    return "\n".join(lines)
