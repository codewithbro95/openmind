# OpenMind Features and Roadmap

This is the living feature ledger for OpenMind Core. Every new feature should be added here when it lands, and roadmap items should move into shipped sections as they are implemented.

## Product Principle

OpenMind is a local AI memory engine for user-approved folders.

Core loop:

```text
Local file -> extract text -> clean text -> chunk -> embed -> store -> search -> answer with sources
```

Current boundaries:

- No desktop UI.
- No browser extension.
- No cloud sync.
- No file automation.
- No deleting, moving, or modifying user files.
- No plugin marketplace.

## Shipped Features

### Core CLI

- `openmind init`
- `openmind setup`
- `openmind status`
- `openmind flush`
- `openmind uninstall`
- `openmind uninstall --yes --package`
- `openmind source add <path>`
- `openmind source list`
- `openmind source remove <id>`

### Local Storage

- Stores app data under `~/.openmind` by default.
- Supports `OPENMIND_HOME` for development and testing.
- Uses SQLite for sources, files, and indexing jobs.
- Uses LanceDB for vector storage.
- Uses `uv` for dependency management with `uv.lock`.
- Can remove OpenMind-owned local data with `openmind uninstall`.
- Can also remove the installed package from the current environment with `--package`.
- Can reset indexed memory and indexing state with `openmind flush`.
- Flush preserves config and sources by default, with `--include-sources` for a fuller reset.

### Source Management

- User-approved folders only.
- Re-adding an existing source reports that it is already registered.
- Recursive folder scanning.
- Ignores noisy folders:
  - `.git`
  - `node_modules`
  - `venv`
  - `.venv`
  - `.env`
  - `__pycache__`
  - `dist`
  - `build`
  - `.cache`
  - hidden folders

### File Support

Supported indexed formats:

- `.txt`
- `.md`
- `.pdf`
- `.docx`
- `.csv`
- `.html`

OpenMind is document-first by default. Source code, JSON config, package metadata, app asset catalogs, and other low-level project internals are not indexed unless a future opt-in mode is added.

Current image files are not indexed. Sample images exist in `data/` only for fixture realism.

### Extraction

- Text extraction.
- Markdown extraction.
- PDF extraction with `pypdf`.
- Automatic scanned-PDF OCR fallback with local RapidOCR + ONNX Runtime.
- DOCX extraction with `python-docx`.
- CSV extraction with `pandas`.
- HTML extraction with BeautifulSoup.

### Ingestion

- Text normalization.
- Character-based chunking.
- Overlapping chunks.
- Source path and metadata retained per chunk.
- Incremental skip for unchanged files that already indexed successfully.
- Metadata-first discovery to avoid hashing every file before indexing starts.
- Content hashing only when a file may have changed.
- Explicit already-indexed reporting for unchanged files that remain accessible.
- Foreground indexing reports skipped/error files with the extraction reason.

### LM Studio Provider

- LM Studio is the only user-facing `0.0.3` provider.
- Native LM Studio REST model listing:
  - `GET /api/v1/models`
- Native LM Studio model loading:
  - `POST /api/v1/models/load`
- OpenAI-compatible chat:
  - `POST /v1/chat/completions`
- OpenAI-compatible responses with reasoning support:
  - `POST /v1/responses`
- OpenAI-compatible embeddings:
  - `POST /v1/embeddings`
- Separate chat model and embedding model config.

### Model Commands

- `openmind models list`
- `openmind models load`
- `openmind models update`
- `openmind provider status`
- Interactive model re-selection from the latest LM Studio model list.
- Saves separate chat and embedding model choices to `~/.openmind/config.toml`.
- Can load newly selected models immediately or save only with `--no-load`.
- Skips model loading when LM Studio reports the model is already loaded.

### Search

- `openmind search "<query>"`
- Uses selected LM Studio embedding model.
- Returns path, score, and snippet.
- Handles LM Studio connection errors without Python tracebacks.

### Ask

- `openmind ask "<question>"`
- Search plus source-grounded answer.
- Streams answer tokens by default.
- Supports `--no-stream`.
- Always shows sources.
- Uses selected LM Studio chat model.
- Uses selected LM Studio embedding model for retrieval.
- Handles LM Studio errors without Python tracebacks.
- Falls back to retrieved snippets if the local model returns no visible answer text.

### Interactive Ask

- Bare `openmind ask` opens an interactive chat session.
- Session history is kept in memory while the process is open.
- Follow-up questions use recent session history for retrieval and prompting.
- Session history is discarded when the process exits.
- Commands inside chat:
  - `/clear`
  - `/exit`
  - `/quit`
- Interactive flags:
  - `--stream/--no-stream`
  - `--show-thinking`
  - `--limit`

### Thinking and Reasoning Display

- `openmind ask "..." --show-thinking`
- Works in one-shot and interactive chat modes.
- Displays provider-returned thinking/reasoning only when LM Studio exposes it.
- Supports:
  - Responses reasoning output.
  - `reasoning_content`
  - `thinking`
  - visible `<think>...</think>` blocks.
- If no reasoning is returned, OpenMind says so and still returns the answer.

### Background Indexing

- `openmind index start`
- `openmind index status`
- `openmind index status --once`
- `openmind index pause`
- `openmind index resume`
- `openmind index stop`
- Two-phase indexing:
  - Discovery.
  - Indexing.
- Live status table.
- Live `Already indexed` count for unchanged indexed files.
- SQLite-backed indexing job state.
- Worker logs under `~/.openmind/logs/index-<job-id>.log`.
- Pause/stop take effect after the current file finishes.
- Progress is capped at `100.0%`.

### Developer Logs

- Structured OpenMind logs:
  - `~/.openmind/logs/openmind.log`
- Index worker logs:
  - `~/.openmind/logs/index-<job-id>.log`
- Commands:
  - `openmind dev logs`
  - `openmind dev logs --no-follow --lines 40`
  - `openmind dev logs --log all`
  - `openmind dev logs --lm-studio`
- LM Studio log mode runs:
  - `lms log stream`

### Test Data

- `data/` folder with local indexing fixtures.
- Includes text, Markdown, JSON, CSV, HTML, JavaScript, PDF, PNG, and JPEG samples.
- Only supported document-first formats and PDFs are indexed in `0.0.3`.

## Known Limits

- Pause and stop cannot interrupt a file already inside extraction or an LM Studio embedding request.
- Image files are not indexed.
- Default scanned-PDF OCR can be installed through `uv`; optional OCRmyPDF mode still needs local OCRmyPDF, Tesseract, and Ghostscript.
- No persistent chat history yet.
- No file watcher yet.
- No ranking tuning beyond vector search.
- No hybrid keyword/vector search yet.
- No UI.
- No non-LM Studio user-facing provider yet.
- No automatic model download flow yet.
- No source enable/disable command yet.
- No command to clear or rebuild LanceDB tables yet.
- No explicit failed-file retry command yet.

## Roadmap

### 0.0.x Stabilization

- Improve indexing error reporting.
- Add failed-file inspection command.
- Add retry failed files command.
- Add rebuild index command.
- Add source enable/disable.
- Add source stats.
- Add index job log shortcut.
- Add faster cancellation checks around embedding batches.
- Add clearer model-loaded status.

### 0.0.4 Retrieval Quality

- Hybrid search: vector plus keyword/BM25.
- Better snippets around matched content.
- Deduplicate chunks from the same file in search results.
- Configurable chunk size and overlap.
- Better code-aware chunking.
- Better PDF page metadata.
- Better CSV/table summaries.

### 0.0.5 Local Memory Quality

- Persistent conversation sessions.
- Session list/resume/delete commands.
- Saved user notes about answers.
- Better source citation formatting.
- Answer confidence and missing-evidence notices.
- Per-source indexing policies.

### 0.0.6 File Coverage

- OCR for screenshots and image files.
- Advanced OCR backend option such as PaddleOCR.
- Image metadata indexing.
- Audio transcript ingestion.
- Email export ingestion.
- More document formats.

### 0.0.7 Local Service

- FastAPI local API.
- Local web UI or desktop UI can connect to the same engine.
- Background worker process management.
- File watcher for incremental indexing.

### Future Providers

- Ollama.
- llama.cpp.
- Generic OpenAI-compatible endpoint.
- Optional cloud providers.

Provider rule: new providers should plug into the existing embedding and answer interfaces without changing the ingestion, storage, or retrieval pipeline.

## Feature Update Rule

When a feature lands:

1. Add it to `Shipped Features`.
2. Remove or adjust any matching `Roadmap` item.
3. Add any important caveat to `Known Limits`.
4. Update `README.md` only if the feature affects normal user workflow.
5. Update `TECHNICAL_SPEC.md` if the feature changes architecture, schema, or interfaces.
