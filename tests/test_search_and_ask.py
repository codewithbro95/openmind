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


class TopicSwitchEngine(OpenMindEngine):
    def __init__(self, home):
        super().__init__(
            paths=AppPaths(
                home=home,
                config_path=home / "config.toml",
                sqlite_path=home / "openmind.sqlite",
                lancedb_path=home / "lancedb",
                logs_path=home / "logs",
            ),
            embeddings=HashEmbeddingProvider(),
            answer_provider=FakeStreamingAnswerProvider(),
        )
        self.search_queries: list[str] = []

    def search(self, query, limit=5):
        self.search_queries.append(query)
        if "invoice" in query.lower():
            return [
                SearchResult(
                    id="chunk_invoice",
                    path="/docs/invoice.pdf",
                    file_name="invoice.pdf",
                    title="Invoice",
                    text="The invoice total is $125.",
                    snippet="The invoice total is $125.",
                    score=0.94,
                    chunk_index=0,
                )
            ]
        return FakeVectorStore().search([], limit=limit)


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


def test_each_chat_turn_retrieves_context_for_its_current_question(tmp_path):
    engine = TopicSwitchEngine(tmp_path)
    session = engine.create_chat_session()

    _, first_sources = engine.ask_with_sources(
        "What is in the holiday plan?",
        session=session,
    )
    second_stream, second_sources = engine.ask_stream_with_sources(
        "What is the invoice total?",
        session=session,
    )
    list(second_stream)

    assert engine.search_queries == [
        "What is in the holiday plan?",
        "What is the invoice total?",
    ]
    assert first_sources[0].path == "/docs/holiday.md"
    assert second_sources[0].path == "/docs/invoice.pdf"


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
