from openmind.core.models import SearchResult
from openmind.core.config import AppPaths
from openmind.core.engine import OpenMindEngine
from openmind.embeddings.provider import HashEmbeddingProvider
from openmind.llm.answer import ContextOnlyAnswerProvider
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
    def stream_answer(self, question, context, show_thinking=False, history=None):
        yield "The answer uses retrieved context."


def test_search_service_returns_ranked_results():
    service = SearchService(HashEmbeddingProvider(), FakeVectorStore())

    results = service.search("holiday plan", limit=1)

    assert len(results) == 1
    assert results[0].path == "/docs/holiday.md"
    assert results[0].score == 0.91


def test_context_only_answer_returns_sources():
    result = FakeVectorStore().search([], limit=1)[0]

    answer = ContextOnlyAnswerProvider().answer("What do I know about the holiday plan?", [result])

    assert "No LLM provider is configured" in answer
    assert "/docs/holiday.md" in answer
    assert "Cabin holiday plan" in answer


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


def test_streaming_ask_reports_retrieval_before_model_answer(tmp_path):
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

    assert chunks[0].startswith("Found 1 relevant chunk(s) in local memory.")
    assert "/docs/holiday.md" in chunks[0]
    assert chunks[1] == "The answer uses retrieved context."
