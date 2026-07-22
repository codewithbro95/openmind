from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class SystemIgnoreRule:
    type: str
    value: str
    reason: str

    @property
    def id(self) -> str:
        identity = f"{self.type}:{self.value}".encode("utf-8")
        return f"ign_sys_{hashlib.sha1(identity).hexdigest()[:12]}"


SYSTEM_IGNORE_RULES = (
    SystemIgnoreRule("folder_name", ".git", "Version control internals"),
    SystemIgnoreRule("folder_name", "node_modules", "Installed project dependencies"),
    SystemIgnoreRule("folder_name", "venv", "Python virtual environment"),
    SystemIgnoreRule("folder_name", ".venv", "Python virtual environment"),
    SystemIgnoreRule("folder_name", "__pycache__", "Generated Python cache"),
    SystemIgnoreRule("folder_name", "dist", "Generated build output"),
    SystemIgnoreRule("folder_name", "build", "Generated build output"),
    SystemIgnoreRule("folder_name", ".cache", "Generated cache directory"),
    SystemIgnoreRule("folder_name", ".build", "Generated build output"),
    SystemIgnoreRule("folder_name", "target", "Generated build output"),
    SystemIgnoreRule("folder_name", "coverage", "Generated coverage output"),
    SystemIgnoreRule("folder_name", ".next", "Generated web build output"),
    SystemIgnoreRule("folder_name", ".nuxt", "Generated web build output"),
    SystemIgnoreRule("folder_name", ".turbo", "Generated build cache"),
    SystemIgnoreRule("folder_name", ".svelte-kit", "Generated web build output"),
    SystemIgnoreRule("folder_name", ".pytest_cache", "Generated test cache"),
    SystemIgnoreRule("folder_name", ".mypy_cache", "Generated type-check cache"),
    SystemIgnoreRule("folder_name", ".ruff_cache", "Generated lint cache"),
    SystemIgnoreRule("folder_name", "DerivedData", "Generated Apple build data"),
    SystemIgnoreRule("folder_name", "Assets.xcassets", "Application asset catalog internals"),
    SystemIgnoreRule("file_name", ".DS_Store", "macOS folder metadata"),
    SystemIgnoreRule("file_name", "Thumbs.db", "Windows thumbnail metadata"),
    SystemIgnoreRule("file_name", ".env", "Sensitive environment configuration"),
    SystemIgnoreRule("file_name", "id_rsa", "Sensitive private key"),
    SystemIgnoreRule("file_name", "id_ed25519", "Sensitive private key"),
    SystemIgnoreRule("pattern", "~$*", "Temporary office document"),
    SystemIgnoreRule("pattern", "*.tmp", "Temporary file"),
    SystemIgnoreRule("pattern", "*.part", "Partial download"),
    SystemIgnoreRule("pattern", "*.crdownload", "Partial browser download"),
    SystemIgnoreRule("pattern", "*.swp", "Temporary editor file"),
    SystemIgnoreRule("pattern", "*.pem", "Sensitive key or certificate"),
    SystemIgnoreRule("pattern", "*.key", "Sensitive private key"),
    SystemIgnoreRule("pattern", "*.p12", "Sensitive key archive"),
    SystemIgnoreRule("pattern", "*.sqlite", "Local database file"),
    SystemIgnoreRule("pattern", "*.db", "Local database file"),
    SystemIgnoreRule("hidden_files", "true", "Hidden files and folders"),
)
