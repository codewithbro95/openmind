# OpenMind Core v0.1 Technical Spec

## Goal

Build a Python CLI tool named `openmind` that creates a local AI memory over user-approved folders.

OpenMind Core v0.1 must:

- Index local files from explicitly added folders.
- Extract text from supported file types.
- Normalize and chunk extracted text.
- Embed chunks with a local Sentence Transformers model.
- Store vectors and chunk metadata in LanceDB.
- Store sources, file records, and indexing state in SQLite.
- Search indexed chunks and return file path, score, and snippet.
- Ask questions by retrieving chunks and returning a source-grounded answer.
- Store all app data under `~/.openmind` unless `OPENMIND_HOME` is set.

## Folder Structure

```text
openmind-core/
├── openmind/
│   ├── cli/
│   │   └── main.py
│   ├── core/
│   │   ├── config.py
│   │   ├── engine.py
│   │   └── models.py
│   ├── sources/
│   │   ├── manager.py
│   │   └── scanner.py
│   ├── extractors/
│   │   ├── base.py
│   │   ├── text.py
│   │   ├── pdf.py
│   │   ├── docx.py
│   │   ├── code.py
│   │   ├── tabular.py
│   │   └── html.py
│   ├── ingestion/
│   │   ├── normalizer.py
│   │   └── chunker.py
│   ├── embeddings/
│   │   └── provider.py
│   ├── storage/
│   │   ├── sqlite_store.py
│   │   └── lance_store.py
│   ├── retrieval/
│   │   ├── search.py
│   │   └── context.py
│   └── llm/
│       └── answer.py
├── tests/
├── pyproject.toml
├── README.md
└── TECHNICAL_SPEC.md
```

## Dependencies

Runtime:

- `typer`
- `rich`
- `lancedb`
- `sentence-transformers`
- `pydantic`
- `pypdf`
- `python-docx`
- `beautifulsoup4`
- `pandas`

Development:

- `pytest`

Later, not v0.1:

- `fastapi`
- `uvicorn`
- `watchdog`
- `llama-cpp-python`
- `ollama`

## App Data

Default:

```text
~/.openmind/
├── config.toml
├── openmind.sqlite
├── lancedb/
└── logs/
```

Override for tests or local experiments:

```bash
OPENMIND_HOME=/tmp/openmind-dev openmind init
```

## SQLite Schema

### `sources`

```sql
CREATE TABLE sources (
  id TEXT PRIMARY KEY,
  path TEXT NOT NULL UNIQUE,
  recursive INTEGER NOT NULL DEFAULT 1,
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);
```

### `files`

```sql
CREATE TABLE files (
  id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL,
  path TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  extension TEXT NOT NULL,
  size INTEGER NOT NULL,
  modified_at REAL NOT NULL,
  content_hash TEXT NOT NULL,
  status TEXT NOT NULL,
  indexed_at TEXT,
  error TEXT,
  FOREIGN KEY(source_id) REFERENCES sources(id)
);
```

### `index_runs`

```sql
CREATE TABLE index_runs (
  id TEXT PRIMARY KEY,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  files_seen INTEGER NOT NULL DEFAULT 0,
  files_indexed INTEGER NOT NULL DEFAULT 0,
  files_skipped INTEGER NOT NULL DEFAULT 0,
  errors INTEGER NOT NULL DEFAULT 0
);
```

## LanceDB Schema

Table: `chunks`

Columns:

- `id`: string
- `source_id`: string
- `file_id`: string
- `path`: string
- `file_name`: string
- `extension`: string
- `title`: string
- `text`: string
- `vector`: list[float]
- `chunk_index`: int
- `content_hash`: string
- `modified_at`: float
- `indexed_at`: string
- `metadata`: string containing JSON

## CLI Commands

```bash
openmind init
openmind source add <path>
openmind source list
openmind source remove <id>
openmind index
openmind search "<query>" --limit 5
openmind ask "<question>" --limit 5
openmind status
```

## Core Interfaces

```python
class Extractor:
    def supports(self, path: str) -> bool: ...
    def extract(self, path: str) -> ExtractedDocument: ...

class EmbeddingProvider:
    @property
    def dimension(self) -> int: ...
    def embed(self, texts: list[str]) -> list[list[float]]: ...

class AnswerProvider:
    def answer(self, question: str, context: list[SearchResult]) -> str: ...
```

## Indexing Flow

1. Load enabled sources from SQLite.
2. Scan each source recursively.
3. Ignore unsupported files and noisy folders.
4. Compute file metadata and content hash.
5. Skip unchanged files that were already indexed.
6. Extract text with the matching extractor.
7. Normalize text.
8. Split text into chunks.
9. Embed chunks.
10. Delete old vectors for the file from LanceDB.
11. Store new chunks in LanceDB.
12. Upsert file status in SQLite.

## Search Flow

1. Embed the query.
2. Search LanceDB `chunks`.
3. Return top results with score, file path, title, chunk text snippet, and metadata.

Search must work without an LLM provider.

## Ask Flow

1. Run the search flow for the question.
2. Build a compact context from retrieved chunks.
3. If an answer provider is configured, generate an answer grounded only in context.
4. If no answer provider is configured, return the top retrieved context and sources.
5. Always show sources.

## Acceptance Tests

The first acceptable build must prove:

- `openmind init` creates app data directories and SQLite tables.
- `openmind source add <path>` records a user-approved source.
- `openmind source list` shows recorded sources.
- Scanner finds supported files and ignores noisy folders.
- Extractors turn supported test files into text.
- Chunker creates overlapping chunks with stable source metadata.
- SQLite file records can be inserted and updated.
- Search service can return ranked results with a fake embedding provider and fake vector store.
- Ask mode returns source-grounded context if no LLM provider is configured.
