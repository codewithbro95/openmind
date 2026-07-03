# OpenMind Core v0.1

OpenMind is a local AI memory engine for your computer. It indexes user-approved folders, stores searchable chunks locally, and lets you search or ask questions with sources.

It starts with three jobs:

1. Index local files.
2. Search indexed memory.
3. Ask source-grounded questions.

No UI, cloud sync, browser extension, agent automation, or file-moving behavior is included in v0.1.

## Install for development

```bash
cd openmind-core
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## CLI

```bash
openmind init
openmind source add ~/Documents
openmind source list
openmind index
openmind search "Portugal visa"
openmind ask "What documents do I have about moving to Portugal?"
openmind status
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

## Supported files

`.txt`, `.md`, `.pdf`, `.docx`, `.py`, `.js`, `.ts`, `.json`, `.csv`, and `.html`.

OpenMind ignores noisy or unsafe folders such as `.git`, `node_modules`, `venv`, `.env`, `__pycache__`, `dist`, `build`, `.cache`, and hidden folders.

## Ask mode

`openmind ask` retrieves relevant chunks first. If no answer model is configured, it returns the best retrieved context with sources instead of failing.
