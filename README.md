# OpenMind Core v0.2

OpenMind is a local AI memory engine for your computer. It indexes user-approved folders, stores searchable chunks locally, and lets you search or ask questions with sources.

It starts with three jobs:

1. Index local files.
2. Search indexed memory.
3. Ask source-grounded questions.

No UI, cloud sync, browser extension, agent automation, or file-moving behavior is included in v0.2.

## Install for development

OpenMind uses `uv` for dependency management. If you already have a conda environment named `openmind`, use that environment and let `uv` install the Python packages into it:

```bash
cd openmind-core
conda activate openmind
uv pip install -e ".[dev]"
pytest
```

Why this path: `uv pip install` detects an activated conda environment and installs into it, so you keep your existing env while still getting uv's fast resolver/installer.

If you do not want to use conda, let uv create the project environment:

```bash
cd openmind-core
uv sync --all-extras
uv run pytest
```

Useful dependency commands:

```bash
uv lock                # update uv.lock from pyproject.toml
uv sync --all-extras   # sync a uv-managed .venv
uv pip install -e ".[dev]"  # install into the active conda/venv environment
```

## CLI

Normal users should start with setup:

```bash
openmind setup
```

Setup initializes local storage, checks LM Studio, lets you choose a chat model and embedding model, asks which folders to index, and starts background indexing.

Lower-level commands remain available:

```bash
openmind init
openmind source add ~/Documents
openmind source list
openmind index
openmind index start
openmind index status
openmind search "Portugal visa"
openmind ask "What documents do I have about moving to Portugal?"
openmind status
```

LM Studio commands:

```bash
openmind provider status
openmind models list
openmind models load
```

OpenMind stores application data under `~/.openmind` by default:

```text
~/.openmind/
├── config.toml
├── openmind.sqlite
├── lancedb/
└── logs/
```

For testing or development, set `OPENMIND_HOME` to another directory.

## LM Studio

OpenMind Core v0.2 uses LM Studio as the only user-facing provider.

Start the LM Studio server from the Developer tab, or run:

```bash
lms server start
```

OpenMind uses:

- `GET /api/v1/models` to list local LLM and embedding models.
- `POST /api/v1/models/load` to load selected models.
- `POST /v1/chat/completions` to answer questions.
- `POST /v1/embeddings` to embed chunks and queries.

Saved config:

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

## Supported files

`.txt`, `.md`, `.pdf`, `.docx`, `.py`, `.js`, `.ts`, `.json`, `.csv`, and `.html`.

OpenMind ignores noisy or unsafe folders such as `.git`, `node_modules`, `venv`, `.env`, `__pycache__`, `dist`, `build`, `.cache`, and hidden folders.

## Ask mode

`openmind ask` retrieves relevant chunks first. With LM Studio configured, it uses the selected embedding model for retrieval and selected chat model for the answer. If no chat model is configured, it returns the best retrieved context with sources instead of failing.

## Background Indexing

```bash
openmind index start
openmind index status
openmind index pause
openmind index resume
openmind index stop
```

Indexing has two phases:

1. Discovery: scan enabled sources and count supported files.
2. Indexing: extract, chunk, embed, and store chunks while updating SQLite progress.

`openmind index status` shows a live table with discovered files, processed files, indexed/skipped/failed counts, chunks created, current file, and progress percentage. It keeps refreshing until you press `Ctrl-C`.

For a one-shot status check:

```bash
openmind index status --once
```

If a job stays in `pending` for more than a few seconds, the worker probably failed before it could update SQLite. Worker logs are written under:

```text
~/.openmind/logs/index-<job-id>.log
```

In v0.2, indexing requires LM Studio to be running because embeddings are created through the selected LM Studio embedding model.

Search and ask also use the selected LM Studio embedding model. If LM Studio times out while generating embeddings, OpenMind exits with a short error message instead of a Python traceback.

## Test Data

This repo includes a small `data/` folder with notes, markdown, JSON, CSV, HTML, JavaScript, a sample PDF, and a couple of images.

```bash
openmind source add ./data
openmind index start
openmind index status
openmind search "Portugal move"
```

Image files are included for realism, but v0.2 only indexes supported text-like formats and PDFs.
