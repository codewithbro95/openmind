# OpenMind Core 0.0.6 Technical Spec

## Goal

Build a Python engine, CLI, and authenticated local API named `openmind` that creates local AI memory over user-approved folders and exposes stable product-level capabilities to client applications.

OpenMind Core must:

- Index local files from explicitly added folders.
- Extract text from supported file types.
- Normalize and chunk extracted text.
- Embed chunks with the configured local embedding provider.
- Store vectors and chunk metadata in LanceDB.
- Store sources, file records, and indexing state in SQLite.
- Search indexed chunks and return file path, score, and snippet.
- Ask questions by retrieving chunks and returning a source-grounded answer.
- Store all app data under `~/.openmind` unless `OPENMIND_HOME` is set.
- Use LM Studio as the first user-facing model server for chat, embeddings, and image descriptions.
- Provide first-run setup and background indexing progress.
- Expose a versioned API on loopback for local client applications.
- Require bearer authentication for private API operations.

## Folder Structure

```text
openmind-core/
├── openmind/
│   ├── cli/
│   │   └── main.py
│   ├── api/
│   │   ├── app.py
│   │   ├── auth.py
│   │   ├── deps.py
│   │   ├── files.py
│   │   ├── schemas.py
│   │   └── routes/
│   │       ├── system.py
│   │       ├── models.py
│   │       ├── sources.py
│   │       ├── indexing.py
│   │       ├── memory.py
│   │       └── actions.py
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
│   │   ├── ocr.py
│   │   ├── image.py
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
│   │       ├── images.py
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
├── API.md
├── README.md
└── TECHNICAL_SPEC.md
```

## Dependencies

Runtime:

- `typer`
- `rich`
- `questionary`
- `fastapi`
- `uvicorn`
- `lancedb`
- `sentence-transformers`
- `pydantic`
- `pypdf`
- `pypdfium2`
- `pillow`
- `rapidocr-onnxruntime`
- `python-docx`
- `beautifulsoup4`
- `pandas`

Development:

- `httpx2`
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

Later, not included yet:

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
    already_indexed_files INTEGER DEFAULT 0,
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
openmind flush
openmind flush --yes --include-sources
openmind uninstall
openmind uninstall --yes --package
```

## Source Removal Flow

`openmind source remove <id>` removes OpenMind's access to a source and unindexes its memory. It never modifies or deletes the original folder.

1. Refuse removal while a background indexing job is unfinished.
2. Mark the source disabled so concurrent foreground indexing cannot commit new records.
3. Delete every LanceDB chunk with the source ID.
4. Delete the source's SQLite file records and source record in one SQLite transaction.
5. Report the file-record and chunk counts removed.

File indexing verifies that its source is still enabled when committing its SQLite record. If a source was disabled concurrently, any chunks produced by that indexing operation are deleted. During initialization, OpenMind also removes orphan file records and chunks left by source removals performed by older versions.

## Setup Flow

`openmind setup` must:

1. Initialize `~/.openmind` if needed.
2. Check LM Studio at `http://localhost:1234`.
3. Display the OpenMind ASCII banner.
4. Present an arrow-key provider selector with LM Studio as the only current option.
5. Fetch `GET /api/v1/models`.
6. Split models by `type`: `llm` for chat and `embedding` for embeddings.
7. Use arrow-key selectors for chat, embedding, and image-description models.
8. Require one embedding model.
9. Load selected models with `POST /api/v1/models/load`.
10. Save config to `~/.openmind/config.toml`.
11. Use a checkbox selector for folders, with a custom-folder option.
12. Start background indexing.
13. Tell the user to run `openmind index status`.

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

[extraction.ocr]
enabled = true
backend = "rapidocr"
min_text_chars_per_page = 80
```

## Uninstall Flow

`openmind uninstall` removes OpenMind-owned local data from the configured app home.

It deletes:

- `config.toml`
- `openmind.sqlite`
- `lancedb/`
- `logs/`
- any other files under `~/.openmind` or `OPENMIND_HOME`

It must not delete:

- user source folders
- LM Studio
- downloaded provider models
- the current Python environment unless `--package` is explicitly passed

Behavior:

1. Show the resolved app home and files that will be removed.
2. Refuse obviously unsafe app home paths such as `/`, the user's home directory, or the current working directory.
3. Require confirmation unless `--yes` is passed.
4. Support `--dry-run`.
5. Request an active indexing job to stop before deletion.
6. Delete the app home directory.
7. If `--package` is passed, run `python -m pip uninstall -y openmind-core` in the current Python environment.
8. If `--package` is not passed, tell the user how to remove the installed Python package separately.

## Flush Flow

`openmind flush` resets indexed memory and indexing state without uninstalling OpenMind.

It deletes:

- SQLite `files` records
- SQLite `index_jobs` records
- SQLite `index_runs` records
- LanceDB vectors and chunks
- log files

It keeps by default:

- `config.toml`
- saved source folder records
- user source folders and files
- provider apps and downloaded models
- the installed Python package

If `--include-sources` is passed, it also deletes saved source folder records from SQLite. It still must not delete the actual folders or files that were indexed.

Behavior:

1. Show the resolved app home and what will be removed.
2. Show current counts for sources, file records, indexed files, index jobs, and index runs.
3. Require confirmation unless `--yes` is passed.
4. Support `--dry-run`.
5. Request an active indexing job to stop and wait briefly before deleting state.
6. Abort if the active indexing job does not stop.
7. Clear SQLite index state.
8. Reset the LanceDB directory.
9. Clear log files.
10. Tell the user to run `openmind index start` to rebuild memory.

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

## OCR Fallback

PDF extraction is two-stage:

1. Extract embedded text with `pypdf`.
2. Measure whether the text is usable.
3. If text is empty, too sparse, or mostly unusual characters, try local OCR.
4. Render PDF pages with `pypdfium2` and OCR them with RapidOCR.
5. Continue the normal pipeline: normalize, chunk, embed, and store in LanceDB.

Default config:

```toml
[extraction.ocr]
enabled = true
backend = "rapidocr"
min_text_chars_per_page = 80
```

OCR metadata is stored on chunks:

```json
{
  "file_type": "pdf",
  "extraction_method": "ocr",
  "ocr_engine": "rapidocr-onnxruntime+pypdfium2",
  "ocr_used": true,
  "page_count": 12
}
```

If OCR dependencies are missing or OCR fails, extraction records `ocr_error` metadata. The indexer marks an otherwise empty PDF as skipped with that error and continues indexing other files. Optional `ocrmypdf` backend support remains available for users who install OCRmyPDF, Tesseract, and Ghostscript separately.

## Image Indexing

Standalone image files are converted to searchable text, then processed by the normal ingestion pipeline.

Image extraction flow:

1. Keep the original image on disk.
2. Read image metadata such as width, height, mode, format, file size, EXIF, and safe image info fields.
3. Send the image plus an indexing prompt to the configured local model server endpoint.
4. Generate a concise search-oriented image description.
5. Run local OCR when available.
6. Combine description, OCR text, and searchable metadata text.
7. Normalize, chunk, embed, and store the resulting text in LanceDB.

OpenMind must not store raw image bytes in LanceDB.

Default config:

```toml
[extraction.images]
enabled = true
model = "ggml-org/SmolVLM-500M-Instruct-GGUF"
ocr_enabled = true
max_new_tokens = 220
```

Image chunk metadata includes:

```json
{
  "file_type": "image",
  "raw_image_stored": false,
  "image_description_model": "ggml-org/SmolVLM-500M-Instruct-GGUF",
  "image_ocr_used": true,
  "image_width": 1200,
  "image_height": 800,
  "image_format": "JPEG",
  "image_exif": {
    "Make": "Example Camera"
  }
}
```

LM Studio is the current model server implementation for image descriptions. The first recommended vision model is `ggml-org/SmolVLM-500M-Instruct-GGUF`. Future providers should keep the same extractor interface and storage contract.

Image metadata must be JSON serializable before storage. Binary metadata fields such as ICC profiles are summarized, not stored as raw bytes.

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
- `POST /api/v1/models/unload`
- `POST /api/v1/chat`

User-facing model loading must call `GET /api/v1/models` first and skip `POST /api/v1/models/load` when the selected model already has loaded instances.

OpenAI-compatible API:

- `POST /v1/chat/completions`
- `POST /v1/responses`
- `POST /v1/embeddings`

Multimodal image descriptions also use `POST /v1/chat/completions`, with image bytes sent only to the local model server request as a data URL. Those bytes are not persisted by OpenMind.

Ask consumes message and reasoning events from the native chat endpoint. Reasoning is disabled by default and enabled only when `--reasoning` or API `reasoning = true` is explicitly requested. OpenMind maps the boolean to a reasoning setting supported by the selected model.

`openmind models update` re-runs provider and model selection after setup:

1. Initialize OpenMind if needed.
2. Ask for provider selection. LM Studio is the only current provider.
3. Fetch `GET /api/v1/models`.
4. Split models into chat, embedding, and vision/image-capable lists.
5. Let the user choose a chat model, or search-only mode.
6. Require one embedding model.
7. Let the user choose an image description model or disable image indexing.
8. Unless `--no-load` is passed, compute the previous OpenMind model keys that are absent from the new selection.
9. Resolve those models' loaded instance IDs with `GET /api/v1/models` and unload each instance with `POST /api/v1/models/unload`.
10. Save the selected keys to `~/.openmind/config.toml`.
11. Load the selected models unless `--no-load` is passed.

Only models from OpenMind's previous configuration are eligible for automatic unloading. Unchanged selections and unrelated models loaded directly in LM Studio are not unloaded. When `--no-load` is used, OpenMind updates configuration without changing model-server memory.

`openmind ask` streams by default:

- normal Ask uses native `POST /api/v1/chat` with `stream = true`
- interactive follow-ups use the previous native `response_id`
- `--reasoning/--no-reasoning` controls model reasoning and displays native reasoning events when enabled
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
4. Indexing phase: compare path, size, and modified time against SQLite records.
5. Skip unchanged files that were already indexed, and count them as already indexed.
6. If metadata changed, compute content hash.
7. If content hash is unchanged, update file metadata and keep existing chunks.
8. If content hash changed or the file is new, extract text with the matching extractor.
9. Normalize text.
10. Split text into chunks.
11. Embed chunks with the selected LM Studio embedding model.
12. Delete old vectors for the file from LanceDB.
13. Store new chunks in LanceDB.
14. Upsert file status in SQLite.
15. Update `index_jobs` progress after each file, including the already-indexed count.

OpenMind should tell the user when unchanged files are already indexed and accessible. This is separate from generic skipped files, because skipped files may also include files where no text could be extracted.

Discovery should be metadata-first. It should not compute content hashes for every discovered file before indexing starts, because that makes large folders appear stuck and wastes work for unchanged files.

Default scanning is document-first plus supported images. OpenMind should index human-facing files such as `.txt`, `.md`, `.pdf`, `.docx`, `.csv`, `.html`, `.png`, `.jpg`, `.jpeg`, `.webp`, `.bmp`, `.tif`, and `.tiff`. It should not index source code, JSON config/package files, generated build artifacts, app asset catalogs such as `Assets.xcassets`, dependency folders, or other low-level project internals unless a future opt-in code indexing mode is added.

## Search Flow

1. Embed the query.
2. Search LanceDB `chunks`.
3. Return top results with score, file path, title, chunk text snippet, and metadata.

Search requires an embedding provider. Normal setup uses LM Studio embeddings.

## Ask Flow

1. Run the search flow for the question.
2. Build a compact context from retrieved chunks.
3. If an LM Studio chat model is configured, generate an answer grounded only in context.
4. If no answer provider is configured, return retrieved snippets without embedding source paths in the answer.
5. Return the answer as GitHub-flavored Markdown.
6. Keep generated answer text separate from structured retrieval sources.
7. Append deduplicated `file://` source links only in the CLI presentation layer.

Interactive CLI and API chat use LM Studio's native stateful `POST /api/v1/chat` endpoint. The first turn stores the provider conversation and captures its `response_id`; follow-ups send only the current question, current retrieved evidence, and `previous_response_id`. OpenMind retains a bounded local history only to improve retrieval queries. One-shot CLI Ask remains stateless.

The synchronous API identifies Ask output with `format = "markdown"`, returns an opaque OpenMind `session_id`, and accepts that ID on follow-ups. The streaming API emits the session ID and Markdown format in its initial `meta` event. `reasoning` defaults to false and controls whether model reasoning is generated and returned. Sources remain available only through the structured `sources` field or SSE event, not appended to generated API text. Search output is unchanged.

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

No Celery, Redis, external queue, or daemon manager is included.

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

## Local API

`openmind serve` starts a single-process FastAPI application at `127.0.0.1:8765`. The CLI does not expose a host option; remote network binding is outside the `0.0.6` security model.

The public liveness route is:

```text
GET /health
```

All product routes are versioned under `/api/v1` and require:

```http
Authorization: Bearer <token>
```

The API token is generated with Python's `secrets` module, stored at `~/.openmind/api_token`, restricted to mode `0600` on POSIX platforms, and compared with `secrets.compare_digest`. The server reads the current token for authenticated requests so rotation takes effect without a restart. Token values must not be written to OpenMind or Uvicorn access logs.

Protected capabilities:

- system and indexing status
- provider status and model discovery
- validated model selection and loading
- source listing, addition, and removal
- background indexing start, pause, resume, status, and stop
- search with structured source records
- stateful synchronous and server-sent-event Ask, including structured source events
- opt-in model reasoning for API clients
- indexed file and chunk details
- opening an indexed file in its default operating-system application

The open-file action accepts only a generated file ID. Before launching an OS application, OpenMind must verify that the file record is indexed, the file still exists, and its fully resolved path remains beneath an enabled source directory.

API schemas reject unknown request fields. Queries, questions, paths, model-key lists, result limits, and file IDs are bounded and validated. Browser CORS is disabled by default. `--allow-origin` accepts exact HTTP or HTTPS origins and refuses wildcard, credential-bearing, path-bearing, query-bearing, or fragment-bearing values.

The API must not expose:

- API token values in responses other than the explicit CLI token command
- arbitrary local paths for open or read actions
- raw files or raw image bytes
- embedding vectors
- raw SQLite or LanceDB operations
- manual chunk insertion
- manual embedding or extractor operations
- shell command execution

FastAPI lifespan initializes one shared `OpenMindEngine` before requests are accepted. Route handlers call engine capabilities rather than reaching around the engine into database implementation details, except read-only indexed document lookup needed to expose sanitized chunk text.

The client contract and examples are documented in [API.md](API.md).

### Runtime Configuration Synchronization

The API keeps one shared engine instance, but the CLI can update `config.toml` from another process. Configuration saves use an atomic same-directory file replacement. Before each authenticated API request, the engine fingerprints the complete config snapshot and reloads only when it changed. Reloading rebuilds the chat, embedding, image-description, extractor, and provider clients together so status and inference use one consistent configuration.

## Acceptance Tests

The first acceptable build must prove:

- `openmind init` creates app data directories and SQLite tables.
- `openmind source add <path>` records a user-approved source.
- `openmind source list` shows recorded sources.
- Removing a source deletes only its SQLite records and LanceDB chunks while preserving user files.
- Source removal cannot race an unfinished background indexing job.
- Initialization cleans indexed data orphaned by legacy source removal behavior.
- Scanner finds supported files and ignores noisy folders.
- Extractors turn supported test files into text.
- Image extractor stores generated descriptions/OCR text, not raw image bytes.
- Chunker creates overlapping chunks with stable source metadata.
- SQLite file records can be inserted and updated.
- Search service can return ranked results with a fake embedding provider and fake vector store.
- Ask mode returns source-grounded context if no LLM provider is configured.
- LM Studio client can list and load models with mocked API responses.
- Config can save and load selected provider/model settings.
- SQLite can create and update indexing job status.
- LM Studio ask returns a clear message when the server is unreachable.
- Public health works without a token while all `/api/v1` routes reject missing or invalid tokens.
- The OpenAPI schema declares bearer security for private routes.
- API token files use private permissions and can be rotated.
- The server CLI always binds Uvicorn to `127.0.0.1`.
- Wildcard CORS and malformed request bodies are rejected.
- Search, Ask, streaming Ask, source management, model selection, and indexing controls work through the API.
- Document lookup omits vectors.
- Open-file actions reject files outside enabled source folders.
