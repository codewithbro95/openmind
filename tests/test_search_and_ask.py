from openmind.core.config import AppPaths
from openmind.core.engine import OpenMindEngine
from openmind.core.models import SearchResult
from openmind.embeddings.provider import HashEmbeddingProvider
from openmind.llm.answer import ContextOnlyAnswerProvider
from openmind.retrieval.context import format_sources
from openmind.retrieval.search import SearchService


class FakeVectorStore:
    def initialize(self):
        pass

    def search(self, vector, limit=5):
        return [
            SearchResult(
                id="chunk_1",
                path="/docs/holiday.md",
                file_name="holiday.md",
                title="holiday",
                text="Cabin holiday plan includes trail maps and meal prep.",
                snippet="Cabin holiday plan includes trail maps and meal prep.",
                score=0.91,
                chunk_index=0,
                metadata={"extension": ".md"},
            )
        ][:limit]


class FakeStreamingAnswerProvider(ContextOnlyAnswerProvider):
    def stream_answer(
        self,
        question,
        context,
        reasoning=False,
        history=None,
        session=None,
    ):
        yield "The answer uses retrieved context."


def test_search_service_returns_ranked_results():
    service = SearchService(HashEmbeddingProvider(), FakeVectorStore())

    results = service.search("holiday plan", limit=1)

    assert len(results) == 1
    assert results[0].path == "/docs/holiday.md"
    assert results[0].score == 0.91


def test_context_only_answer_returns_context_without_source_text():
    result = FakeVectorStore().search([], limit=1)[0]

    answer = ContextOnlyAnswerProvider().answer("What do I know about the holiday plan?", [result])

    assert "No LLM provider is configured" in answer
    assert "Cabin holiday plan" in answer
    assert "/docs/holiday.md" not in answer
    assert "Sources" not in answer


def test_ask_sources_are_markdown_file_links():
    result = FakeVectorStore().search([], limit=1)[0]

    assert format_sources([result]) == ["[/docs/holiday.md](file:///docs/holiday.md)"]


def test_context_answer_handles_multiple_chunks_from_one_source():
    result = FakeVectorStore().search([], limit=1)[0]
    second_chunk = result.model_copy(update={"id": "chunk_2", "chunk_index": 1})

    answer = ContextOnlyAnswerProvider().answer("What is in this file?", [result, second_chunk])

    assert answer.count("Cabin holiday plan includes trail maps and meal prep.") == 2


def test_conversation_search_query_includes_recent_history():
    engine = OpenMindEngine(embeddings=HashEmbeddingProvider())

    query = engine._conversation_search_query(
        "What about the checklist?",
        [
            {"role": "user", "content": "Tell me about holiday planning files."},
            {"role": "assistant", "content": "I found checklist notes."},
        ],
    )

    assert "holiday planning files" in query
    assert "checklist notes" in query
    assert "What about the checklist?" in query


def test_ending_chat_session_discards_local_provider_state():
    engine = OpenMindEngine(embeddings=HashEmbeddingProvider())
    session = engine.create_chat_session()
    session.provider_state["response_id"] = "resp_private"

    ended = engine.end_chat_session(session.id)

    assert ended is True
    assert session.provider_state == {}
    assert engine.chat_session(session.id) is None


def test_streaming_ask_starts_with_model_answer_without_retrieval_preamble(tmp_path):
    engine = OpenMindEngine(
        paths=AppPaths(
            home=tmp_path,
            config_path=tmp_path / "config.toml",
            sqlite_path=tmp_path / "openmind.sqlite",
            lancedb_path=tmp_path / "lancedb",
            logs_path=tmp_path / "logs",
        ),
        embeddings=HashEmbeddingProvider(),
        answer_provider=FakeStreamingAnswerProvider(),
        lance_store=FakeVectorStore(),
    )

    chunks = list(engine.ask_stream("What is this about?", limit=1))

    assert chunks == ["The answer uses retrieved context."]
