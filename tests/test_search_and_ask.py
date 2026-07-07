from openmind.core.models import SearchResult
from openmind.core.engine import OpenMindEngine
from openmind.embeddings.provider import HashEmbeddingProvider
from openmind.llm.answer import ContextOnlyAnswerProvider
from openmind.retrieval.search import SearchService


class FakeVectorStore:
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
