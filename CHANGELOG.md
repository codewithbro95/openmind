# Changelog

User-facing changes for each OpenMind Core release.

## Unreleased

- No unreleased changes.

## 0.0.3 - 2026-07-08

- Added automatic OCR for scanned PDFs using Python-installed local OCR.
- Added `PublicWaterMassMailing.pdf` as scanned PDF test data.
- Added clearer indexing output when a file is skipped or extraction fails.
- Added safer Ask behavior when a local model returns no visible answer text.
- Added `openmind flush` to reset indexed memory without uninstalling.
- Added `openmind uninstall` to remove OpenMind-owned local data.
- Added `openmind models update` to change saved LM Studio chat and embedding models.
- Added explicit already-indexed reporting for unchanged files during indexing.
- Improved duplicate source feedback when a folder was already added.
- Improved incremental indexing so unchanged files are skipped quickly.
- Changed default scanning to skip source code, JSON config, and low-level project files.
- Changed model loading to skip models that are already loaded in LM Studio.

## 0.0.2 - 2026-07-04

- Added first-run setup with `openmind setup`.
- Added LM Studio as the default local AI provider.
- Added model commands for listing and loading LM Studio models.
- Added background indexing with live progress.
- Added pause, resume, and stop controls for indexing.
- Added streaming answers by default.
- Added interactive chat mode with bare `openmind ask`.
- Added optional thinking/reasoning display with `--show-thinking`.
- Added developer log viewing with `openmind dev logs`.
- Added graceful LM Studio error messages instead of Python tracebacks.
- Added `uv` dependency management.
- Added sample local test data in `data/`.
- Fixed editable install issues.
- Fixed background indexing startup, pause, stop, and progress display issues.

## 0.0.1 - 2026-07-03

- Added the first OpenMind Python package and CLI.
- Added local app storage under `~/.openmind`.
- Added source folder management.
- Added local file scanning for user-approved folders.
- Added text extraction for common file types.
- Added text normalization and chunking.
- Added local vector storage with LanceDB.
- Added SQLite records for sources, files, and indexing state.
- Added search over indexed local files.
- Added basic ask mode with source-grounded context.
- Added the first README, technical spec, and test suite.
