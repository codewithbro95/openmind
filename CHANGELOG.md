# Changelog

User-facing changes for each OpenMind Core release.

## Unreleased

- Removing a source now removes its indexed memory without deleting the original files.
- The running API now picks up chat, embedding, image, and provider changes made from the CLI.
- Updating models now unloads previous OpenMind models(from the model provider) before loading their replacements.
- Ask responses now format answers, links, and local sources as Markdown.
- Chat now uses faster provider-backed sessions, keeps API sources separate, and lets CLI and API users enable model reasoning when needed while keeping it off by default.

## 0.0.5 - 2026-07-19

- Added `openmind --version` and clearer command descriptions.
- Added arrow-key setup menus, checkbox folder selection, and an OpenMind terminal banner.
- Fixed a bug with custom folder selection so standard folders are not selected automatically.
- Exposing the core functional features over API, added a secure local API so anyone can easily build their own client app on top of OpenMind.
  - Apps can manage models, sources, and indexing, search local memory, stream answers, inspect results, and open indexed files.

## 0.0.4 - 2026-07-15

- Added image indexing through a local LM Studio vision model.
- Added generated image descriptions and optional image OCR text to local memory.
- Added searchable image metadata such as dimensions, format, EXIF, and safe image info fields.
- Kept raw image bytes out of LanceDB; OpenMind stores paths, metadata, text descriptions, OCR text, and embeddings.
- Improved setup folder selection so pasted paths work and duplicate sources are reported clearly.

## 0.0.3 - 2026-07-08

- Added automatic local OCR for scanned PDFs.
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
