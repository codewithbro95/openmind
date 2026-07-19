# Contributing to OpenMind

Thanks for helping build OpenMind.

OpenMind is a local-first AI memory engine. The project should stay simple, inspectable, and respectful of user data. Contributions are welcome when they strengthen that direction.

## Project Principles

- Local data stays local.
- Users explicitly choose which folders are indexed.
- Answers should show sources.
- Search quality comes before answer polish.
- Providers should be replaceable behind small interfaces.
- No hidden scanning, cloud sync, file automation, or file mutation.
- Keep the core boring inside so the product can feel useful outside.

## Development Setup

Use Python 3.11+ and `uv`.

With an existing conda environment:

```bash
conda activate openmind
uv pip install -e ".[dev]"
pytest
```

With a uv-managed environment:

```bash
uv sync --all-extras
uv run pytest
```

Useful commands:

```bash
uv lock
uv sync --all-extras
uv pip install -e ".[dev]"
```

## Running OpenMind Locally

Start LM Studio first:

```bash
lms server start
```

Then run:

```bash
openmind setup
openmind index status
openmind search "holiday plan"
openmind ask "What do my files say about the cabin trip?"
```

For isolated testing, set `OPENMIND_HOME`:

```bash
OPENMIND_HOME=/tmp/openmind-dev openmind setup
```

## Before Opening a Change

Run the test suite:

```bash
pytest
```

Check the user-facing CLI still works for the affected area.

For indexing changes, test at least:

```bash
openmind source add ./data
openmind index start
openmind index status --once
openmind search "holiday plan"
```

For ask changes, test streaming and non-streaming behavior:

```bash
openmind ask "What do my files say about the cabin trip?"
openmind ask "What do my files say about the cabin trip?" --no-stream
```

## Documentation Rules

When a feature lands:

- Add it to [FEATURES.md](FEATURES.md).
- Add a short user-facing note to [CHANGELOG.md](CHANGELOG.md) when it belongs in a release.
- Update [README.md](README.md) if the normal workflow or CLI changes.
- Update [TECHNICAL_SPEC.md](TECHNICAL_SPEC.md) if architecture, schema, provider behavior, or interfaces change.

The changelog should stay brief and readable for users. Put deeper implementation details in the technical spec or pull request discussion.

## Code Style

- Prefer small modules with clear responsibilities.
- Follow the existing Typer and Rich CLI style.
- Use Pydantic models for structured objects when they cross module boundaries.
- Keep provider-specific code inside `openmind/providers/`.
- Keep ingestion, retrieval, and storage provider-agnostic where practical.
- Avoid broad refactors inside feature changes.
- Add comments only when they clarify non-obvious behavior.

## Tests

Tests should be focused and practical.

Add tests when you change:

- CLI behavior.
- Local API routes, authentication, validation, or response schemas.
- SQLite schema or persistence.
- Source scanning.
- Extraction or chunking.
- Embedding or provider behavior.
- Search or ask flows.
- Background indexing job state.

Mock LM Studio for provider tests. Do not require contributors to run a local model just to pass the default test suite.

API changes must preserve the security boundaries documented in [API.md](API.md). Keep the server loopback-only, require authentication for product routes, validate request bodies, and never expose vectors, raw databases, arbitrary filesystem reads, or shell execution.

## Privacy and Safety

OpenMind must not scan the whole computer by default.

Do not add behavior that:

- Indexes folders the user did not approve.
- Uploads file contents to a remote service by default.
- Deletes, moves, renames, or modifies user files.
- Hides sources from answers.
- Silently downloads large models.

If a future feature needs one of those powers, it should be explicit, opt-in, and documented before it ships.

## Good First Contributions

- Improve error messages.
- Add tests around existing behavior.
- Improve snippets and source formatting.
- Add small extractor fixes.
- Improve README examples.
- Add failed-file inspection commands.
- Improve index status and logging output.

## Release Notes

OpenMind uses concise, user-facing changelog entries. Write release notes as short bullets about what changed for users, not as implementation summaries.

## Release Process

OpenMind releases are published from `main`, not from `develop`.

Before a release:

- Update `pyproject.toml` with the new version.
- Update `openmind/__init__.py` with the same version.
- Add a short user-facing section to [CHANGELOG.md](CHANGELOG.md).
- Keep test fixtures, internal refactors, and implementation details out of the changelog unless they affect users directly.
- Merge the release commit from `develop` into `main`.

After the release commit is on `main`, the `Release` workflow runs automatically when `pyproject.toml` changes.

The workflow:

- Refuses to run from any branch except `main`.
- Reads the version from `pyproject.toml`.
- Requires the changelog to contain a matching section.
- Runs the test suite.
- Creates a `vX.Y.Z` git tag.
- Publishes the GitHub Release using the matching changelog notes.
- Publishes the matching package to PyPI when the tag points at the current `main` release commit.

The workflow can also be run manually from the GitHub Actions tab. For the current version, leave the inputs empty. For backfilling an older release, pass:

- `version`: the older version, such as `0.0.1`.
- `target_ref`: the commit that should be tagged for that release.

Backfilled releases still require the target commit to be part of the current `main` history.

## PyPI Publishing

OpenMind publishes to PyPI as `openmind-core`. The installed command is still `openmind`.

PyPI publishing is handled by the `Release` workflow after the GitHub Release is created. It uses PyPI Trusted Publishing, so the repository should not store a long-lived PyPI API token.

The separate `Publish Python Package` workflow exists as a manual fallback for an existing release tag.

One-time PyPI setup:

- Create or log in to a PyPI account.
- Create a pending trusted publisher for project `openmind-core`.
- Set owner to `codewithbro95`.
- Set repository to `openmind`.
- Set workflow filename to `release.yml`.
- Set environment name to `pypi`.

Normal publish flow:

- Merge the release commit to `main`.
- Let the `Release` workflow create the GitHub Release and publish the package to PyPI.

Backfilled GitHub releases are skipped for PyPI unless the release tag points at the current release commit and matches the version in `pyproject.toml`.

After publishing, users can install OpenMind with:

```bash
uv tool install openmind-core
```

or:

```bash
pipx install openmind-core
```
