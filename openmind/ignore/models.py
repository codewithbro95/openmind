from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

IgnoreRuleType = Literal[
    "path",
    "folder_name",
    "file_name",
    "extension",
    "pattern",
    "source_type",
    "max_file_size",
    "hidden_files",
]
IgnoreRuleScope = Literal["global", "source"]


class IgnoreRule(BaseModel):
    id: str
    type: IgnoreRuleType
    value: str
    enabled: bool = True
    scope: IgnoreRuleScope = "global"
    source_id: str | None = None
    reason: str | None = None
    is_system: bool = False
    created_at: str
    updated_at: str


class IgnoreDecision(BaseModel):
    ignored: bool
    rule_id: str | None = None
    rule_type: IgnoreRuleType | None = None
    rule_value: str | None = None
    reason: str | None = None

    @classmethod
    def allowed(cls) -> "IgnoreDecision":
        return cls(ignored=False)

    @classmethod
    def matched(cls, rule: IgnoreRule) -> "IgnoreDecision":
        return cls(
            ignored=True,
            rule_id=rule.id,
            rule_type=rule.type,
            rule_value=rule.value,
            reason=rule.reason or f"Matches {rule.type} rule {rule.value}",
        )
