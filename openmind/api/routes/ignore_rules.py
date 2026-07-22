from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from openmind.api.deps import EngineDependency
from openmind.api.schemas import (
    IgnoreRuleCreateRequest,
    IgnoreRuleDeleteResponse,
    IgnoreRuleListResponse,
    IgnoreRuleMatchResponse,
    IgnoreRuleResponse,
    IgnoreRuleTestRequest,
    IgnoreRuleTestResponse,
    IgnoreRuleUpdateRequest,
)
from openmind.ignore.errors import (
    DuplicateIgnoreRuleError,
    IgnoreRuleError,
    IgnoreRuleNotFoundError,
    ProtectedIgnoreRuleError,
)
from openmind.ignore.models import IgnoreRule

router = APIRouter(prefix="/ignore-rules", tags=["ignore rules"])


@router.get("", response_model=IgnoreRuleListResponse)
def list_ignore_rules(engine: EngineDependency) -> IgnoreRuleListResponse:
    return IgnoreRuleListResponse(rules=[_response(rule) for rule in engine.list_ignore_rules()])


@router.post("", response_model=IgnoreRuleResponse, status_code=status.HTTP_201_CREATED)
def create_ignore_rule(
    request: IgnoreRuleCreateRequest,
    engine: EngineDependency,
) -> IgnoreRuleResponse:
    try:
        values = request.model_dump()
        rule = engine.add_ignore_rule(values.pop("type"), **values)
    except IgnoreRuleError as exc:
        raise _http_error(exc) from exc
    return _response(rule)


@router.patch("/{rule_id}", response_model=IgnoreRuleResponse)
def update_ignore_rule(
    rule_id: str,
    request: IgnoreRuleUpdateRequest,
    engine: EngineDependency,
) -> IgnoreRuleResponse:
    try:
        rule = engine.update_ignore_rule(rule_id, **request.model_dump(exclude_unset=True))
    except IgnoreRuleError as exc:
        raise _http_error(exc) from exc
    return _response(rule)


@router.delete("/{rule_id}", response_model=IgnoreRuleDeleteResponse)
def delete_ignore_rule(rule_id: str, engine: EngineDependency) -> IgnoreRuleDeleteResponse:
    try:
        engine.remove_ignore_rule(rule_id)
    except IgnoreRuleError as exc:
        raise _http_error(exc) from exc
    return IgnoreRuleDeleteResponse(deleted=True, rule_id=rule_id)


@router.post("/test", response_model=IgnoreRuleTestResponse)
def test_ignore_rule(
    request: IgnoreRuleTestRequest,
    engine: EngineDependency,
) -> IgnoreRuleTestResponse:
    decision = engine.test_ignore_path(
        request.path,
        source_id=request.source_id,
        size=request.size,
    )
    matched = None
    if decision.ignored:
        matched = IgnoreRuleMatchResponse(
            id=decision.rule_id or "",
            type=decision.rule_type,
            value=decision.rule_value or "",
            reason=decision.reason,
        )
    return IgnoreRuleTestResponse(ignored=decision.ignored, matched_rule=matched)


def _response(rule: IgnoreRule) -> IgnoreRuleResponse:
    return IgnoreRuleResponse(**rule.model_dump())


def _http_error(exc: IgnoreRuleError) -> HTTPException:
    if isinstance(exc, IgnoreRuleNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, ProtectedIgnoreRuleError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, DuplicateIgnoreRuleError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
