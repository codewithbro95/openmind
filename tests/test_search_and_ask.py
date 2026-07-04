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
                path="/docs/visa.md",
                file_name="visa.md",
                title="visa",
                text="Portuguese job seeker visa requires proof of accommodation.",
                snippet="Portuguese job seeker visa requires proof of accommodation.",
                score=0.91,
                chunk_index=0,
                metadata={"extension": ".md"},
            )
        ][:limit]


def test_search_service_returns_ranked_results():
    service = SearchService(HashEmbeddingProvider(), FakeVectorStore())

    results = service.search("Portugal visa", limit=1)

    assert len(results) == 1
    assert results[0].path == "/docs/visa.md"
    assert results[0].score == 0.91


def test_context_only_answer_returns_sources():
    result = FakeVectorStore().search([], limit=1)[0]

    answer = ContextOnlyAnswerProvider().answer("What do I know about Portugal?", [result])

    assert "No LLM provider is configured" in answer
    assert "/docs/visa.md" in answer
    assert "Portuguese job seeker visa" in answer


def test_conversation_search_query_includes_recent_history():
    engine = OpenMindEngine(embeddings=HashEmbeddingProvider())

    query = engine._conversation_search_query(
        "What about the appointment?",
        [
            {"role": "user", "content": "Tell me about Portugal visa files."},
            {"role": "assistant", "content": "I found appointment notes."},
        ],
    )

    assert "Portugal visa files" in query
    assert "appointment notes" in query
    assert "What about the appointment?" in query
