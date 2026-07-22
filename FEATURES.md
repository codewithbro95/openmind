# OpenMind Features and Roadmap

This is the living feature ledger for OpenMind Core. Every new feature should be added here when it lands, and roadmap items should move into implemented sections as they are completed.

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

## Implemented Features

### Core CLI

- `openmind --version` and `openmind -V`
- `openmind init`
- `openmind setup`
- `openmind status`
- `openmind flush`
- `openmind uninstall`
- `openmind uninstall --yes --package`
- `openmind source add <path>`
- `openmind source list`
- `openmind source remove <id>`
- Descriptive top-level help text for every command.
- Large OpenMind ASCII banner during first-run setup.
- Arrow-key selection menus for providers and models.
- Checkbox folder selection with arrow keys and the Space key.
- Shared interactive prompt styling across setup and model updates.

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

- Removing a source also removes its SQLite file records and LanceDB memory chunks.
- Original source folders and files are never deleted.
- Indexed data left by sources removed with older versions is cleaned up automatically.
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
- `.png`
- `.jpg`
- `.jpeg`
- `.webp`
- `.bmp`
- `.tif`
- `.tiff`

OpenMind is document-first. Source code, HTML, JSON config, package metadata, app asset catalogs, and other low-level project internals are not supported indexed formats. Markdown remains the supported format for high-level project documentation.

OpenMind removes stale indexed memory for unsupported formats during startup without deleting or modifying the original files.

Image files are indexed by generating text descriptions through a local vision model endpoint and embedding that text like any other document chunk.

### Extraction

- Text extraction.
- Markdown extraction.
- PDF extraction with `pypdf`.
- Automatic scanned-PDF OCR fallback with local RapidOCR + ONNX Runtime.
- DOCX extraction with `python-docx`.
- CSV extraction with `pandas`.
- HTML extraction with BeautifulSoup.
- Image description extraction through a local LM Studio vision model.
- Optional image OCR text extraction with RapidOCR.
- Searchable image metadata extraction for dimensions, format, EXIF, and safe image info fields.
- Raw image bytes are not stored in LanceDB.

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

- LM Studio is currently the only user-facing provider.
- Native LM Studio REST model listing:
  - `GET /api/v1/models`
- Native LM Studio model loading:
  - `POST /api/v1/models/load`
- Native stateful chat with response-ID continuation and reasoning events:
  - `POST /api/v1/chat`
- OpenAI-compatible embeddings:
  - `POST /v1/embeddings`
- OpenAI-compatible multimodal chat for image descriptions:
  - `POST /v1/chat/completions`
- Separate chat, embedding, and image description model config.

### Model Commands

- `openmind models list`
- `openmind models load`
- `openmind models update`
- `openmind provider status`
- Interactive model re-selection from the latest LM Studio model list.
- Saves separate chat, embedding, and image description model choices.
- Can load newly selected models immediately or save only with `--no-load`.
- Unloads previous OpenMind model selections that are no longer used before loading replacements.
- Leaves unrelated models loaded independently in LM Studio untouched.
- Skips model loading when LM Studio reports the model is already loaded.

### Search

- `openmind search "<query>"`
- Uses selected LM Studio embedding model.
- Returns path, score, and snippet.
- Handles LM Studio connection errors without Python tracebacks.

### Ask

- `openmind ask "<question>"`
- Search plus source-grounded answer.
- Uses GitHub-flavored Markdown for headings, lists, tables, code blocks, and links.
- Identifies synchronous and streaming API answers as Markdown.
- Keeps generated API text separate from structured source records.
- Makes model reasoning opt-in for API clients and disabled by default.
- Streams answer tokens by default.
- Supports `--no-stream`.
- Always shows sources.
- Uses selected LM Studio chat model.
- Uses selected LM Studio embedding model for retrieval.
- Handles LM Studio errors without Python tracebacks.
- Falls back to retrieved snippets if the local model returns no visible answer text.

### Interactive Ask

- Bare `openmind ask` opens an interactive chat session.
- Uses the provider's stateful chat continuation ID instead of resending full model history.
- Runs fresh vector retrieval for every chat message, even when the topic changes within a session.
- API requests return an opaque session ID that clients can reuse or explicitly end.
- Session history is discarded when the process exits.
- Commands inside chat:
  - `/clear`
  - `/exit`
  - `/quit`
- Interactive flags:
  - `--stream/--no-stream`
  - `--reasoning/--no-reasoning`
  - `--limit`

### Thinking and Reasoning Display

- `openmind ask "..." --reasoning`
- Works in one-shot and interactive chat modes.
- Enables and displays reasoning only when the selected model supports it.
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

### Local API

- `openmind serve` starts the API on `127.0.0.1:8765`.
- Versioned client contract under `/api/v1`.
- Public `GET /health` liveness endpoint.
- Bearer authentication for every private endpoint.
- Random local API token stored with private file permissions.
- `openmind api token` shows the client token.
- `openmind api token --rotate` invalidates the existing token.
- Running API clients automatically see provider and model changes saved by the CLI.
- Status and model-provider inspection.
- Model listing, validated selection, and loading.
- Source listing, creation, and removal.
- Start, status, pause, resume, and stop indexing operations.
- Search responses with paths, snippets, scores, metadata, and stable file IDs.
- Source-grounded synchronous Ask responses.
- Server-sent-event streaming for Ask.
- Indexed document and chunk inspection without vectors.
- Safe open-file action restricted to indexed files inside enabled sources.
- Interactive OpenAPI documentation.
- Explicit browser origins through repeatable `--allow-origin`; wildcard CORS is refused.
- No raw SQLite, LanceDB, embedding, vector, extractor, or arbitrary-path endpoints.

### Test Data

- `data/` folder with local indexing fixtures.
- Includes supported document and image samples plus source/config fixtures that verify excluded formats stay unindexed.

## Known Limits

- Pause and stop cannot interrupt a file already inside extraction or an LM Studio embedding request.
- Image indexing requires a local vision model served through LM Studio.
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
- API access is intentionally local-only; remote binding is not supported.

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

### Retrieval Quality

- Hybrid search: vector plus keyword/BM25.
- Better snippets around matched content.
- Deduplicate chunks from the same file in search results.
- Configurable chunk size and overlap.
- Better code-aware chunking.
- Better PDF page metadata.
- Better CSV/table summaries.

### Local Memory Quality

- Persistent conversation sessions.
- Session list/resume/delete commands.
- Saved user notes about answers.
- Better source citation formatting.
- Answer confidence and missing-evidence notices.
- Per-source indexing policies.

### File Coverage

- OCR for screenshots and image files.
- Advanced OCR backend option such as PaddleOCR.
- More advanced image metadata filtering and ranking.
- Audio transcript ingestion.
- Email export ingestion.
- More document formats.

### Local Service Extensions

- Background worker process management.
- File watcher for incremental indexing.
- Optional event stream for indexing progress.

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
