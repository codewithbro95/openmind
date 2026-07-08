from __future__ import annotations

from collections.abc import Iterator

from openmind.core.models import SearchResult
from openmind.llm.answer import AnswerProvider
from openmind.providers.lmstudio.client import LMStudioClient
from openmind.providers.lmstudio.errors import LMStudioConnectionError, LMStudioModelError
from openmind.retrieval.context import build_context, format_sources


class LMStudioLLMProvider(AnswerProvider):
    def __init__(self, client: LMStudioClient, model: str):
        self.client = client
        self.model = model

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
        messages = self._messages(question, context, history=history)
        try:
            if not self.client.is_model_loaded(self.model):
                return (
                    "The selected chat model is not loaded.\n"
                    "Run:\n"
                    "openmind models load"
                )
            if show_thinking:
                result = self.client.respond_with_reasoning(self.model, messages)
            else:
                result = self.client.chat(self.model, messages)
        except LMStudioConnectionError as exc:
            return str(exc)
        except LMStudioModelError as exc:
            return str(exc)

        source_lines = "\n".join(f"- {source}" for source in sources)
        sections: list[str] = []
        if show_thinking and result.reasoning:
            sections.extend(["Thinking:", result.reasoning.strip(), ""])
        elif show_thinking:
            sections.extend(
                [
                    "Thinking:",
                    "The selected model did not return explicit thinking/reasoning text.",
                    "",
                ]
            )
        sections.extend([result.content.strip(), "", "Sources:", source_lines])
        return "\n".join(sections).strip()

    def stream_answer(
        self,
        question: str,
        context: list[SearchResult],
        show_thinking: bool = False,
        history: list[dict[str, str]] | None = None,
    ) -> Iterator[str]:
        if not context:
            yield "I did not find any indexed documents that match this question."
            return

        sources = format_sources(context)
        messages = self._messages(question, context, history=history)
        try:
            if not self.client.is_model_loaded(self.model):
                yield "The selected chat model is not loaded.\nRun:\nopenmind models load"
                return

            stream = (
                self.client.respond_stream(self.model, messages)
                if show_thinking
                else self.client.chat_stream(self.model, messages)
            )
            thinking_started = False
            answer_started = False
            thinking_seen = False
            hidden_thinking_indicator_seen = False

            for delta in stream:
                if show_thinking and delta.reasoning:
                    if not thinking_started:
                        thinking_started = True
                        yield "Thinking:\n"
                    thinking_seen = True
                    yield delta.reasoning
                elif delta.reasoning and not hidden_thinking_indicator_seen and not answer_started:
                    hidden_thinking_indicator_seen = True
                    yield "Generating...\n"
                if delta.content:
                    if not answer_started and hidden_thinking_indicator_seen and not show_thinking:
                        answer_started = True
                        yield "\nAnswer:\n"
                    elif show_thinking and not answer_started:
                        answer_started = True
                        if thinking_started:
                            yield "\n\nAnswer:\n"
                        else:
                            yield "Answer:\n"
                    else:
                        answer_started = True
                    yield delta.content

            if show_thinking and not thinking_seen:
                if answer_started:
                    yield "\n\n"
                yield "Thinking:\nThe selected model did not return explicit thinking/reasoning text."
        except LMStudioConnectionError as exc:
            yield str(exc)
            return
        except LMStudioModelError as exc:
            yield str(exc)
            return

        source_lines = "\n".join(f"- {source}" for source in sources)
        yield f"\n\nSources:\n{source_lines}"

    def _messages(
        self,
        question: str,
        context: list[SearchResult],
        history: list[dict[str, str]] | None = None,
    ) -> list[dict[str, str]]:
        context_text = build_context(context)
        messages = [
            {
                "role": "system",
                "content": (
                    "You are OpenMind's local answer layer. OpenMind has already searched "
                    "the user's indexed local files and provided the retrieved evidence below. "
                    "Use that evidence to answer the user's question. Do not say you cannot "
                    "access files, documents, or local data when relevant evidence is present "
                    "in the provided context. If the evidence is partial, answer what it "
                    "supports and say what was not found. If the evidence truly does not "
                    "answer the question, say that clearly. Keep answers concise, grounded, "
                    "and tied to source paths. Use prior conversation only to understand "
                    "follow-up questions. Do not introduce yourself, name the model, or "
                    "describe your identity."
                ),
            },
        ]
        if history:
            messages.extend(_trim_history(history))
        messages.append(
            {
                "role": "user",
                "content": (
                    f"Question:\n{question}\n\n"
                    "Retrieved local file evidence:\n"
                    "The following excerpts come from files OpenMind already indexed and "
                    "retrieved for this question. Treat them as the available file evidence.\n\n"
                    f"{context_text}\n\n"
                    "Answer from the retrieved evidence. Start with the direct answer, then "
                    "mention the relevant source path or paths. Do not invent details outside "
                    "the evidence."
                ),
            }
        )
        return messages


def _trim_history(history: list[dict[str, str]], max_messages: int = 10) -> list[dict[str, str]]:
    allowed_roles = {"user", "assistant"}
    trimmed = []
    for item in history[-max_messages:]:
        role = item.get("role", "")
        content = item.get("content", "")
        if role in allowed_roles and content:
            trimmed.append({"role": role, "content": content[-4000:]})
    return trimmed
