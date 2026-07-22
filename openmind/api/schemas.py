from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

QueryText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
ModelKey = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
ChatSessionId = Annotated[str, StringConstraints(pattern=r"^chat_[0-9a-f]{16}$")]
IgnoreRuleTypeValue = Literal[
    "path",
    "folder_name",
    "file_name",
    "extension",
    "pattern",
    "source_type",
    "max_file_size",
    "hidden_files",
]
IgnoreRuleScopeValue = Literal["global", "source"]


class ApiSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HealthResponse(ApiSchema):
    status: str
    version: str


class StatusResponse(ApiSchema):
    status: str
    version: str
    provider: str
    chat_model: str | None
    embedding_model: str | None
    image_model: str | None
    sources: int
    indexed_files: int
    indexed_chunks: int
    indexing_state: str
    last_index_job_status: str | None
    watcher_state: str
    queued_watch_jobs: int


class WatchStatusResponse(ApiSchema):
    state: str
    sources: list[str]
    queued_jobs: int
    current_file: str | None
    last_event_at: str | None
    last_indexed_at: str | None
    errors: list[str]


class ProviderStatusResponse(ApiSchema):
    provider: str
    reachable: bool
    message: str


class ProviderInfo(ApiSchema):
    name: str
    display_name: str
    configured: bool


class ProvidersResponse(ApiSchema):
    providers: list[ProviderInfo]


class ModelInfo(ApiSchema):
    key: str
    name: str
    type: str
    loaded: bool
    supports_images: bool
    max_context_length: int | None = None
    quantization: dict[str, Any] | None = None


class ModelsResponse(ApiSchema):
    provider: str
    chat_models: list[ModelInfo]
    embedding_models: list[ModelInfo]
    image_models: list[ModelInfo]


class ModelLoadRequest(ApiSchema):
    model_keys: list[ModelKey] | None = Field(default=None, min_length=1, max_length=3)


class ModelLoadResult(ApiSchema):
    model: str
    status: str
    skipped: bool


class ModelLoadResponse(ApiSchema):
    results: list[ModelLoadResult]


class ModelSelectionRequest(ApiSchema):
    chat_model: ModelKey | None = None
    embedding_model: ModelKey
    image_model: ModelKey | None = None
    load: bool = True


class ModelSelectionResponse(ApiSchema):
    provider: str
    chat_model: str | None
    embedding_model: str
    image_model: str | None
    unload_results: list[ModelLoadResult]
    load_results: list[ModelLoadResult]


class SourceCreateRequest(ApiSchema):
    path: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=4096),
    ]
    recursive: bool = True


class SourceResponse(ApiSchema):
    id: str
    path: str
    recursive: bool
    enabled: bool
    created_at: str


class SourceListResponse(ApiSchema):
    sources: list[SourceResponse]


class SourceRemovalResponse(ApiSchema):
    source_id: str
    source_path: str
    files_removed: int
    chunks_removed: int
    user_files_deleted: bool = False


class IgnoreRuleCreateRequest(ApiSchema):
    type: IgnoreRuleTypeValue
    value: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4096)]
    enabled: bool = True
    scope: IgnoreRuleScopeValue = "global"
    source_id: str | None = Field(default=None, max_length=64)
    reason: str | None = Field(default=None, max_length=500)


class IgnoreRuleUpdateRequest(ApiSchema):
    type: IgnoreRuleTypeValue | None = None
    value: Annotated[
        str | None,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=4096),
    ] = None
    enabled: bool | None = None
    scope: IgnoreRuleScopeValue | None = None
    source_id: str | None = Field(default=None, max_length=64)
    reason: str | None = Field(default=None, max_length=500)


class IgnoreRuleResponse(ApiSchema):
    id: str
    type: IgnoreRuleTypeValue
    value: str
    enabled: bool
    scope: IgnoreRuleScopeValue
    source_id: str | None
    reason: str | None
    is_system: bool
    created_at: str
    updated_at: str


class IgnoreRuleListResponse(ApiSchema):
    rules: list[IgnoreRuleResponse]


class IgnoreRuleDeleteResponse(ApiSchema):
    deleted: bool
    rule_id: str


class IgnoreRuleTestRequest(ApiSchema):
    path: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=4096),
    ]
    source_id: str | None = Field(default=None, max_length=64)
    size: int | None = Field(default=None, ge=0)


class IgnoreRuleMatchResponse(ApiSchema):
    id: str
    type: IgnoreRuleTypeValue
    value: str
    reason: str | None


class IgnoreRuleTestResponse(ApiSchema):
    ignored: bool
    matched_rule: IgnoreRuleMatchResponse | None = None


class IndexJobResponse(ApiSchema):
    job_id: str | None
    state: str
    total_files: int
    processed_files: int
    indexed_files: int
    skipped_files: int
    already_indexed_files: int
    failed_files: int
    chunks_created: int
    current_file: str | None
    error: str | None
    progress: float
    started_at: str | None
    completed_at: str | None
    updated_at: str | None


class SearchRequest(ApiSchema):
    query: QueryText
    limit: int = Field(default=5, ge=1, le=50)


class SearchResultResponse(ApiSchema):
    id: str
    file_id: str
    source_id: str
    score: float
    source_type: str
    path: str
    file_name: str
    title: str
    snippet: str
    chunk_index: int
    metadata: dict[str, Any]


class SearchResponse(ApiSchema):
    query: str
    results: list[SearchResultResponse]


class AskRequest(ApiSchema):
    question: QueryText
    limit: int = Field(default=5, ge=1, le=20)
    include_sources: bool = True
    reasoning: bool = Field(
        default=False,
        description="Enable the selected model's reasoning capability and return its output.",
    )
    session_id: ChatSessionId | None = None


class AskResponse(ApiSchema):
    format: Literal["markdown"] = "markdown"
    session_id: str
    answer: str
    sources: list[SearchResultResponse]


class ChatSessionResponse(ApiSchema):
    session_id: str
    ended: bool = False


class DocumentChunkResponse(ApiSchema):
    id: str
    text: str
    chunk_index: int
    title: str
    metadata: dict[str, Any]


class DocumentResponse(ApiSchema):
    id: str
    source_id: str
    path: str
    file_name: str
    extension: str
    status: str
    size: int
    modified_at: float
    indexed_at: str | None
    error: str | None
    chunks: list[DocumentChunkResponse]


class OpenFileRequest(ApiSchema):
    file_id: str = Field(pattern=r"^file_[0-9a-f]{16}$")


class OpenFileResponse(ApiSchema):
    opened: bool
    file_id: str
    path: str
