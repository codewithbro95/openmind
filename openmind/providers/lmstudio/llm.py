from __future__ import annotations

from openmind.core.models import SearchResult
from openmind.llm.answer import AnswerProvider
from openmind.providers.lmstudio.client import LMStudioClient
from openmind.providers.lmstudio.errors import LMStudioConnectionError, LMStudioModelError
from openmind.retrieval.context import build_context, format_sources


class LMStudioLLMProvider(AnswerProvider):
    def __init__(self, client: LMStudioClient, model: str):
        self.client = client
        self.model = model

    def answer(self, question: str, context: list[SearchResult]) -> str:
        if not context:
            return "I did not find any indexed documents that match this question."

        sources = format_sources(context)
        context_text = build_context(context)
        messages = [
            {
                "role": "system",
                "content": (
                    "You answer questions using only the provided local file context. "
                    "If the context does not support a claim, say you did not find it. "
                    "Always keep the answer concise and source-grounded."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Question:\n{question}\n\n"
                    f"Local file context:\n{context_text}\n\n"
                    "Answer with a short summary and mention the relevant source paths."
                ),
            },
        ]
        try:
            if not self.client.is_model_loaded(self.model):
                return (
                    "The selected chat model is not loaded.\n"
                    "Run:\n"
                    "openmind models load"
                )
            answer = self.client.chat(self.model, messages)
        except LMStudioConnectionError as exc:
            return str(exc)
        except LMStudioModelError as exc:
            return str(exc)

        source_lines = "\n".join(f"- {source}" for source in sources)
        return f"{answer.strip()}\n\nSources:\n{source_lines}".strip()
