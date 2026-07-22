from __future__ import annotations

import fnmatch
import re
import threading
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from openmind.ignore.defaults import SYSTEM_IGNORE_RULES
from openmind.ignore.errors import (
    DuplicateIgnoreRuleError,
    IgnoreRuleError,
    IgnoreRuleNotFoundError,
    ProtectedIgnoreRuleError,
)
from openmind.ignore.models import IgnoreDecision, IgnoreRule, IgnoreRuleScope, IgnoreRuleType
from openmind.storage.sqlite_store import utc_now

if TYPE_CHECKING:
    from openmind.storage.sqlite_store import SQLiteStore

SUPPORTED_SOURCE_TYPES = {
    "image": {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"},
    "document": {".txt", ".md", ".pdf", ".docx", ".csv"},
    "text": {".txt"},
    "markdown": {".md"},
    "pdf": {".pdf"},
    "word": {".docx"},
    "csv": {".csv"},
}
MAX_RULE_VALUE_LENGTH = 4096
MAX_REASON_LENGTH = 500
SIZE_PATTERN = re.compile(r"^(\d+(?:\.\d+)?)\s*(B|KB|MB|GB)?$", re.IGNORECASE)
SIZE_MULTIPLIERS = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3}


class IgnoreEngine:
    def __init__(self, store: SQLiteStore | None = None):
        self.store = store
        self._cache_lock = threading.Lock()
        self._cached_rules: list[IgnoreRule] | None = None
        self._rules_cached_at = 0.0
        self._source_roots: dict[str, Path | None] = {}

    def list_rules(self, enabled_only: bool = False) -> list[IgnoreRule]:
        if self.store is not None:
            return self.store.list_ignore_rules(enabled_only=enabled_only)
        now = utc_now()
        return [
            IgnoreRule(
                id=rule.id,
                type=rule.type,
                value=rule.value,
                reason=rule.reason,
                is_system=True,
                created_at=now,
                updated_at=now,
            )
            for rule in SYSTEM_IGNORE_RULES
        ]

    def add_rule(
        self,
        rule_type: str,
        value: str,
        *,
        enabled: bool = True,
        scope: str = "global",
        source_id: str | None = None,
        reason: str | None = None,
    ) -> IgnoreRule:
        store = self._required_store()
        normalized = self.validate_rule(
            rule_type,
            value,
            scope=scope,
            source_id=source_id,
            reason=reason,
        )
        if store.find_ignore_rule(
            normalized["type"],
            normalized["value"],
            normalized["scope"],
            normalized["source_id"],
        ):
            raise DuplicateIgnoreRuleError("An equivalent ignore rule already exists.")
        now = utc_now()
        rule = IgnoreRule(
            id=f"ign_{uuid.uuid4().hex[:16]}",
            type=normalized["type"],
            value=normalized["value"],
            enabled=enabled,
            scope=normalized["scope"],
            source_id=normalized["source_id"],
            reason=normalized["reason"],
            created_at=now,
            updated_at=now,
        )
        store.add_ignore_rule(rule)
        self._invalidate_cache()
        return rule

    def update_rule(self, rule_id: str, **changes: Any) -> IgnoreRule:
        store = self._required_store()
        existing = store.ignore_rule_by_id(rule_id)
        if existing is None:
            raise IgnoreRuleNotFoundError(f"Unknown ignore rule: {rule_id}")
        if existing.is_system:
            raise ProtectedIgnoreRuleError("System ignore rules cannot be changed.")
        values = existing.model_dump()
        values.update(changes)
        if values["type"] is None or values["value"] is None or values["scope"] is None:
            raise IgnoreRuleError("Rule type, value, and scope cannot be null.")
        normalized = self.validate_rule(
            values["type"],
            values["value"],
            scope=values["scope"],
            source_id=values["source_id"],
            reason=values["reason"],
        )
        duplicate = store.find_ignore_rule(
            normalized["type"],
            normalized["value"],
            normalized["scope"],
            normalized["source_id"],
        )
        if duplicate is not None and duplicate.id != rule_id:
            raise DuplicateIgnoreRuleError("An equivalent ignore rule already exists.")
        updated = existing.model_copy(
            update={
                **normalized,
                "enabled": bool(values["enabled"]),
                "updated_at": utc_now(),
            }
        )
        store.update_ignore_rule(updated)
        self._invalidate_cache()
        return updated

    def remove_rule(self, rule_id: str) -> IgnoreRule:
        store = self._required_store()
        existing = store.ignore_rule_by_id(rule_id)
        if existing is None:
            raise IgnoreRuleNotFoundError(f"Unknown ignore rule: {rule_id}")
        if existing.is_system:
            raise ProtectedIgnoreRuleError("System ignore rules cannot be removed.")
        store.delete_ignore_rule(rule_id)
        self._invalidate_cache()
        return existing

    def should_ignore(
        self,
        path: str | Path,
        source_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        *,
        refresh: bool = False,
    ) -> IgnoreDecision:
        candidate = Path(path).expanduser().resolve(strict=False)
        source_root = self._source_root(source_id)
        relative = self._relative_path(candidate, source_root)
        for rule in self._active_rules(refresh=refresh):
            if rule.scope == "source" and rule.source_id != source_id:
                continue
            try:
                if self._matches(rule, candidate, relative, metadata or {}):
                    return IgnoreDecision.matched(rule)
            except (OSError, ValueError):
                continue
        return IgnoreDecision.allowed()

    def validate_rule(
        self,
        rule_type: str,
        value: str,
        *,
        scope: str,
        source_id: str | None,
        reason: str | None,
    ) -> dict[str, Any]:
        supported_types = set(IgnoreRuleType.__args__)
        if rule_type not in supported_types:
            raise IgnoreRuleError(f"Unsupported ignore rule type: {rule_type}")
        if scope not in set(IgnoreRuleScope.__args__):
            raise IgnoreRuleError("Ignore rule scope must be global or source.")
        cleaned = value.strip()
        if not cleaned or len(cleaned) > MAX_RULE_VALUE_LENGTH or "\x00" in cleaned:
            raise IgnoreRuleError("Ignore rule value must be between 1 and 4096 characters.")
        cleaned_reason = reason.strip() if reason else None
        if cleaned_reason and len(cleaned_reason) > MAX_REASON_LENGTH:
            raise IgnoreRuleError("Ignore rule reason cannot exceed 500 characters.")
        if scope == "source":
            if not source_id:
                raise IgnoreRuleError("A source-specific rule requires source_id.")
            if self.store is not None and self.store.source_by_id(source_id) is None:
                raise IgnoreRuleError(f"Unknown source id: {source_id}")
        else:
            source_id = None

        if rule_type == "path":
            cleaned = str(Path(cleaned).expanduser().resolve(strict=False))
        elif rule_type == "extension":
            cleaned = cleaned.lower()
            if not cleaned.startswith("."):
                cleaned = f".{cleaned}"
            if any(character in cleaned for character in ("/", "\\", "*", "?", "[", "]")):
                raise IgnoreRuleError("An extension must look like .pdf or .mp4.")
        elif rule_type in {"folder_name", "file_name"}:
            if (
                Path(cleaned).name != cleaned
                or any(separator in cleaned for separator in ("/", "\\"))
                or cleaned in {".", ".."}
            ):
                raise IgnoreRuleError(f"{rule_type} must be a single name, not a path.")
        elif rule_type == "source_type":
            cleaned = cleaned.lower()
            if cleaned not in SUPPORTED_SOURCE_TYPES:
                choices = ", ".join(sorted(SUPPORTED_SOURCE_TYPES))
                raise IgnoreRuleError(f"Source type must be one of: {choices}")
        elif rule_type == "max_file_size":
            _parse_size(cleaned)
            cleaned = re.sub(r"\s+", "", cleaned).upper()
        elif rule_type == "hidden_files":
            if cleaned.lower() not in {"true", "yes", "1"}:
                raise IgnoreRuleError("hidden_files value must be true.")
            cleaned = "true"
        return {
            "type": rule_type,
            "value": cleaned,
            "scope": scope,
            "source_id": source_id,
            "reason": cleaned_reason,
        }

    def _matches(
        self,
        rule: IgnoreRule,
        path: Path,
        relative: Path | None,
        metadata: dict[str, Any],
    ) -> bool:
        parts = relative.parts if relative is not None else path.parts
        if rule.type == "path":
            ignored_path = Path(rule.value)
            return path == ignored_path or path.is_relative_to(ignored_path)
        if rule.type == "folder_name":
            folder_parts = parts[:-1] if path.suffix else parts
            return rule.value in folder_parts
        if rule.type == "file_name":
            return path.name == rule.value
        if rule.type == "extension":
            return path.name.lower().endswith(rule.value)
        if rule.type == "pattern":
            relative_text = relative.as_posix() if relative is not None else path.name
            return fnmatch.fnmatchcase(path.name, rule.value) or fnmatch.fnmatchcase(
                relative_text,
                rule.value,
            )
        if rule.type == "source_type":
            return path.suffix.lower() in SUPPORTED_SOURCE_TYPES[rule.value]
        if rule.type == "max_file_size":
            size = metadata.get("size")
            if size is None and path.is_file():
                size = path.stat().st_size
            return size is not None and int(size) > _parse_size(rule.value)
        if rule.type == "hidden_files":
            return any(part.startswith(".") for part in parts)
        return False

    def _source_root(self, source_id: str | None) -> Path | None:
        if self.store is None or source_id is None:
            return None
        with self._cache_lock:
            if source_id in self._source_roots:
                return self._source_roots[source_id]
        source = self.store.source_by_id(source_id)
        root = Path(source.path) if source is not None else None
        with self._cache_lock:
            self._source_roots[source_id] = root
        return root

    def _active_rules(self, *, refresh: bool = False) -> list[IgnoreRule]:
        now = time.monotonic()
        with self._cache_lock:
            if (
                not refresh
                and self._cached_rules is not None
                and now - self._rules_cached_at < 1.0
            ):
                return self._cached_rules
        rules = self.list_rules(enabled_only=True)
        with self._cache_lock:
            self._cached_rules = rules
            self._rules_cached_at = now
        return rules

    def _invalidate_cache(self) -> None:
        with self._cache_lock:
            self._cached_rules = None
            self._rules_cached_at = 0.0

    @staticmethod
    def _relative_path(path: Path, source_root: Path | None) -> Path | None:
        if source_root is None:
            return None
        try:
            return path.relative_to(source_root)
        except ValueError:
            return None

    def _required_store(self) -> SQLiteStore:
        if self.store is None:
            raise RuntimeError("Ignore rule management requires SQLite storage.")
        return self.store


def _parse_size(value: str) -> int:
    match = SIZE_PATTERN.fullmatch(value.strip())
    if match is None:
        raise IgnoreRuleError("File size must look like 100MB, 2GB, or 500KB.")
    amount = float(match.group(1))
    unit = (match.group(2) or "B").upper()
    size = int(amount * SIZE_MULTIPLIERS[unit])
    if size <= 0:
        raise IgnoreRuleError("Maximum file size must be greater than zero.")
    return size
