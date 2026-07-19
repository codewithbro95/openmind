# OpenMind Core API

The OpenMind Core API lets local client applications manage sources, control indexing, search local memory, and ask source-grounded questions without knowing about SQLite, LanceDB, extractors, embeddings, or model-provider internals.

The first API contract is available at:

```text
http://127.0.0.1:8765/api/v1
```

Interactive OpenAPI documentation is available at `http://127.0.0.1:8765/docs` while the server is running.

## Start the server

Complete `openmind setup` first, then run:

```bash
openmind serve
```

The server always binds to `127.0.0.1`. A different port can be selected without exposing the API to the network:

```bash
openmind serve --port 9000
```

## Authentication

OpenMind generates a cryptographically random API token at:

```text
~/.openmind/api_token
```

The token file is restricted to the current operating-system user on platforms that support POSIX permissions. Show the token with:

```bash
openmind api token
```

Send it with every `/api/v1` request:

```http
Authorization: Bearer <openmind-api-token>
```

`GET /health` is the only unauthenticated endpoint. It returns only liveness and the OpenMind version.

Rotate a token if it may have been exposed:

```bash
openmind api token --rotate
```

Rotation immediately invalidates the previous token. The running API server picks up the new token automatically.

## First request

```bash
TOKEN="$(openmind api token)"

curl http://127.0.0.1:8765/api/v1/status \
  -H "Authorization: Bearer $TOKEN"
```

Search local memory:

```bash
curl http://127.0.0.1:8765/api/v1/search \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"cabin packing list","limit":5}'
```

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Public liveness and version check |
| `GET` | `/api/v1/status` | OpenMind, model, memory, and indexing status |
| `GET` | `/api/v1/providers` | Available model providers |
| `GET` | `/api/v1/providers/status` | Current provider connectivity |
| `GET` | `/api/v1/models` | Available chat, embedding, and image models |
| `POST` | `/api/v1/models/load` | Load configured or explicitly selected models |
| `PUT` | `/api/v1/models/selection` | Save validated model choices and optionally load them |
| `GET` | `/api/v1/sources` | List user-approved source folders |
| `POST` | `/api/v1/sources` | Add a source folder |
| `DELETE` | `/api/v1/sources/{source_id}` | Remove a source and its indexed memory |
| `POST` | `/api/v1/index/start` | Start or return the active background indexing job |
| `GET` | `/api/v1/index/status` | Read indexing progress |
| `POST` | `/api/v1/index/pause` | Request indexing pause |
| `POST` | `/api/v1/index/resume` | Resume paused indexing |
| `POST` | `/api/v1/index/stop` | Request indexing stop |
| `POST` | `/api/v1/search` | Search indexed local memory |
| `POST` | `/api/v1/ask` | Return an answer with structured sources |
| `POST` | `/api/v1/ask/stream` | Stream answer text as server-sent events |
| `DELETE` | `/api/v1/chat/sessions/{session_id}` | End an in-memory chat session |
| `GET` | `/api/v1/documents/{file_id}` | Inspect an indexed file and its text chunks |
| `POST` | `/api/v1/actions/open` | Open a validated indexed file in its default OS app |

## Sources

Add a folder:

```json
{
  "path": "/Users/example/Documents",
  "recursive": true
}
```

OpenMind resolves the path and rejects missing files, non-directory paths, and duplicate sources. Removing a source also removes its file records and searchable chunks from OpenMind, but never deletes the original folder or files. Source removal returns the number of file records and memory chunks removed and is refused while an indexing job is active.

```json
{
  "source_id": "src_0123456789ab",
  "source_path": "/Users/example/Documents",
  "files_removed": 42,
  "chunks_removed": 318,
  "user_files_deleted": false
}
```

## Model selection

The running API automatically reloads model and provider settings when `openmind models update` changes the local configuration. Status, Ask, search, image indexing, model loading, and provider requests therefore use the newly selected chat, embedding, image, and provider settings without restarting `openmind serve`.

The model fields returned by `/api/v1/status` are the models currently selected for OpenMind to use. The `loaded` fields returned by `/api/v1/models` show whether each model is currently loaded in the model server.

`GET /api/v1/models` separates chat, embedding, and image-capable models. Save selections with:

```json
{
  "chat_model": "qwen-model-key",
  "embedding_model": "nomic-embedding-key",
  "image_model": "smolvlm-model-key",
  "load": true
}
```

The API validates every key against models reported by the configured provider. Set `chat_model` to `null` for search-only mode or `image_model` to `null` to disable image indexing. An embedding model is required.

With `load: true`, OpenMind unloads previously selected models that are no longer needed before loading the new selection. It does not unload unrelated models that were loaded independently in LM Studio. The response includes separate `unload_results` and `load_results` arrays. With `load: false`, only the saved selection changes; loaded model instances are left untouched.

## Search and Ask

Search request:

```json
{
  "query": "OAuth error screenshot",
  "limit": 10
}
```

Search results contain a `file_id`, `source_id`, path, score, snippet, source type, chunk index, and safe metadata. They never contain raw vectors or raw image bytes.

Ask request:

```json
{
  "question": "Do I have screenshots related to login errors?",
  "limit": 8,
  "include_sources": true,
  "reasoning": false,
  "session_id": null
}
```

The first request creates an in-memory chat session and returns its `session_id`. Send that ID with follow-up requests to continue the same provider conversation without resending the full message history. Every request still searches local memory using its current question and sends fresh retrieved evidence to the model, so changing topics within a session does not reuse the first turn's sources. Sessions expire after four hours of inactivity and end when the API process stops; clients can end one earlier with `DELETE /api/v1/chat/sessions/{session_id}`.

The synchronous response marks `format` as `markdown`, returns only the generated Markdown in `answer`, and keeps source details in the separate `sources` field. The answer does not contain an appended Sources section. `reasoning` defaults to `false`; set it to `true` to enable the selected model's reasoning capability and include its reasoning output. Unsupported models return a clear error. Search responses are unchanged.

Use `/api/v1/ask/stream` with the same request body for server-sent events. Concatenate the `text` values from every `delta` event, then render the result as Markdown:

```text
event: meta
data: {"format":"markdown","session_id":"chat_...","reasoning":false}

event: delta
data: {"text":"partial Markdown answer"}

event: sources
data: {"sources":[{"file_id":"file_...","path":"/Users/example/Documents/notes.md"}]}

event: done
data: {"session_id":"chat_..."}
```

## Open indexed files safely

The open action accepts an indexed `file_id`, not an arbitrary path:

```json
{
  "file_id": "file_0123456789abcdef"
}
```

Before opening anything, OpenMind verifies that the database record is indexed, the file still exists, and its resolved path remains inside an enabled source folder. The API does not expose delete, move, edit, shell-command, or arbitrary-path actions.

## Browser clients and CORS

Cross-origin browser access is disabled by default. Allow only the exact development or application origin that needs access:

```bash
openmind serve --allow-origin http://localhost:3000
```

Repeat `--allow-origin` for multiple origins. Wildcards, credentials embedded in origins, paths, query strings, and fragments are rejected. Native desktop, mobile, editor, and command-line clients do not need CORS configuration.

## Error responses

OpenMind uses standard HTTP status codes:

- `400` for an invalid product-level operation.
- `401` for a missing or invalid bearer token.
- `403` for a recognized but forbidden local action.
- `404` when a source, job, document, or indexed file is unavailable.
- `409` when a source folder is already registered.
- `422` when a request does not match the documented schema.
- `503` when the configured model provider cannot complete a request.

Error bodies use FastAPI's standard `detail` field. Client applications should not depend on internal exception text.

## Security boundaries

- The server binds only to `127.0.0.1`; there is no public-host option.
- Private endpoints require bearer authentication, including on localhost.
- API tokens are generated locally, stored outside the project, omitted from logs, and compared in constant time.
- CORS is disabled unless exact origins are explicitly supplied.
- Request schemas reject unknown fields and bound text and result sizes.
- Only user-approved source folders can be indexed or opened.
- The API does not expose SQLite, LanceDB, embeddings, vectors, extractor calls, worker internals, raw file downloads, or raw image bytes.

These boundaries are intentional. Client applications consume OpenMind capabilities while storage and provider implementations remain replaceable.
