# OpenMind Core v0.2 Technical Spec

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
- Use LM Studio as the first and only user-facing LLM and embedding provider.
- Provide first-run setup and background indexing progress.

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
│   ├── providers/
│   │   └── lmstudio/
│   │       ├── client.py
│   │       ├── llm.py
│   │       ├── embeddings.py
│   │       ├── models.py
│   │       └── errors.py
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

Dependency management:

- `uv`
- `pyproject.toml`
- `uv.lock`

OpenMind supports two install paths:

```bash
conda activate openmind
uv pip install -e ".[dev]"
```

or:

```bash
uv sync --all-extras
```

Later, not v0.2:

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

### `index_jobs`

```sql
CREATE TABLE index_jobs (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    total_files INTEGER DEFAULT 0,
    processed_files INTEGER DEFAULT 0,
    indexed_files INTEGER DEFAULT 0,
    skipped_files INTEGER DEFAULT 0,
    failed_files INTEGER DEFAULT 0,
    total_chunks INTEGER DEFAULT 0,
    current_file TEXT,
    error TEXT,
    started_at TEXT,
    completed_at TEXT,
    updated_at TEXT
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
openmind setup
openmind init
openmind source add <path>
openmind source list
openmind source remove <id>
openmind index
openmind index start
openmind index status
openmind index pause
openmind index resume
openmind index stop
openmind models list
openmind models load
openmind models update
openmind provider status
openmind search "<query>" --limit 5
openmind ask "<question>" --limit 5
openmind status
```

## Setup Flow

`openmind setup` must:

1. Initialize `~/.openmind` if needed.
2. Check LM Studio at `http://localhost:1234`.
3. Present provider selection with LM Studio as the only v0.2 option.
4. Fetch `GET /api/v1/models`.
5. Split models by `type`: `llm` for chat and `embedding` for embeddings.
6. Ask the user to choose one chat model when available.
7. Require one embedding model.
8. Load selected models with `POST /api/v1/models/load`.
9. Save config to `~/.openmind/config.toml`.
10. Ask which folders to index.
11. Start background indexing.
12. Tell the user to run `openmind index status`.

## Config Format

```toml
[provider]
name = "lmstudio"
base_url = "http://localhost:1234"
api_token_env = "LM_API_TOKEN"

[models]
chat_model = "selected-chat-model-key"
embedding_model = "selected-embedding-model-key"

[indexing]
auto_start_after_setup = true
background = true
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

## LM Studio Provider

`LMStudioClient`:

```python
class LMStudioClient:
    def health_check(self) -> bool: ...
    def list_models(self) -> list[LMStudioModel]: ...
    def load_model(self, model_key: str, context_length: int | None = None) -> dict: ...
    def load_model_if_needed(
        self,
        model_key: str,
        context_length: int | None = None,
    ) -> dict: ...
    def chat(self, model: str, messages: list[dict]) -> LMStudioChatResult: ...
    def respond_with_reasoning(
        self,
        model: str,
        messages: list[dict],
        effort: str = "medium",
    ) -> LMStudioChatResult: ...
    def embed(self, model: str, texts: list[str]) -> list[list[float]]: ...
```

Native REST API:

- `GET /api/v1/models`
- `POST /api/v1/models/load`

User-facing model loading must call `GET /api/v1/models` first and skip `POST /api/v1/models/load` when the selected model already has loaded instances.

OpenAI-compatible API:

- `POST /v1/chat/completions`
- `POST /v1/responses`
- `POST /v1/embeddings`

`openmind ask --show-thinking` uses the Responses endpoint with a `reasoning` payload and displays reasoning only when LM Studio returns explicit reasoning/thinking text. OpenMind also handles chat responses that expose fields such as `reasoning_content`, `thinking`, or a visible `<think>...</think>` block.

`openmind models update` re-runs provider and model selection after setup:

1. Initialize OpenMind if needed.
2. Ask for provider selection. LM Studio is the only v0.2 provider.
3. Fetch `GET /api/v1/models`.
4. Split models into chat and embedding lists.
5. Let the user choose a chat model, or search-only mode.
6. Require one embedding model.
7. Save the selected keys to `~/.openmind/config.toml`.
8. Load the selected models unless `--no-load` is passed.

`openmind ask` streams by default:

- normal ask uses OpenAI-compatible `POST /v1/chat/completions` with `stream = true`
- `--show-thinking` uses OpenAI-compatible `POST /v1/responses` with `stream = true`
- `--no-stream` uses the previous full-response behavior
- sources are appended after streaming finishes

Interactive ask:

- `openmind ask` with no question starts an interactive chat session.
- Session history is held in memory only.
- Follow-up retrieval uses the current user question plus recent session history.
- The LLM receives recent user/assistant messages plus fresh local file context for the current turn.
- `/clear` resets session history.
- `/exit` and `/quit` close the session.

## Indexing Flow

1. Load enabled sources from SQLite.
2. Discovery phase: scan each source recursively and count supported files.
3. Ignore unsupported files and noisy folders.
4. Indexing phase: compute metadata and content hash.
5. Skip unchanged files that were already indexed.
6. Extract text with the matching extractor.
7. Normalize text.
8. Split text into chunks.
9. Embed chunks with the selected LM Studio embedding model.
10. Delete old vectors for the file from LanceDB.
11. Store new chunks in LanceDB.
12. Upsert file status in SQLite.
13. Update `index_jobs` progress after each file.

## Search Flow

1. Embed the query.
2. Search LanceDB `chunks`.
3. Return top results with score, file path, title, chunk text snippet, and metadata.

Search requires an embedding provider. In v0.2, normal setup uses LM Studio embeddings.

## Ask Flow

1. Run the search flow for the question.
2. Build a compact context from retrieved chunks.
3. If an LM Studio chat model is configured, generate an answer grounded only in context.
4. If no answer provider is configured, return the top retrieved context and sources.
5. Always show sources.

## Background Indexing

`openmind index start` creates an `index_jobs` row and starts:

```bash
openmind index worker --job-id <id>
```

as a background subprocess.

The worker accepts `--job-id` and writes stdout/stderr to:

```text
~/.openmind/logs/index-<job-id>.log
```

If a job remains `pending` for more than 30 seconds, a later `openmind index start` marks it failed and creates a new job.

Pause behavior:

- `openmind index pause` sets `pause_requested`.
- The worker finishes the current file, then changes the state to `paused`.
- The worker remains paused until `openmind index resume` changes the state back to `running`.
- `openmind index stop` can stop a paused or running worker.

`openmind index status` reads SQLite and displays a live Rich table until the user exits with `Ctrl-C`.

`openmind index status --once` prints one snapshot and exits.

The status table reports:

- state
- total files
- processed files
- indexed files
- skipped files
- failed files
- chunks created
- progress percentage
- current file

Progress formula:

```text
processed_files / total_files * 100
```

No Celery, Redis, external queue, or daemon manager is included in v0.2.

## LM Studio Failure Handling

Search and ask must catch provider errors and print concise CLI messages instead of Python tracebacks.

For embedding requests, OpenMind uses LM Studio's OpenAI-compatible `POST /v1/embeddings` endpoint and normalizes newlines to spaces before sending input text.

## Developer Logs

OpenMind writes structured JSONL logs to:

```text
~/.openmind/logs/openmind.log
```

Index worker stdout/stderr is written to:

```text
~/.openmind/logs/index-<job-id>.log
```

CLI:

```bash
openmind dev logs
openmind dev logs --no-follow --lines 40
openmind dev logs --log all
openmind dev logs --lm-studio
```

`--lm-studio` runs `lms log stream`, matching LM Studio's own development guidance for inspecting model input.

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
- LM Studio client can list and load models with mocked API responses.
- Config can save and load selected provider/model settings.
- SQLite can create and update indexing job status.
- LM Studio ask returns a clear message when the server is unreachable.
