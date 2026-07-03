from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel


DEFAULT_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_LMSTUDIO_BASE_URL = "http://localhost:1234"


@dataclass(frozen=True)
class AppPaths:
    home: Path
    config_path: Path
    sqlite_path: Path
    lancedb_path: Path
    logs_path: Path

    @classmethod
    def from_env(cls) -> "AppPaths":
        home = Path(os.environ.get("OPENMIND_HOME", "~/.openmind")).expanduser()
        return cls(
            home=home,
            config_path=home / "config.toml",
            sqlite_path=home / "openmind.sqlite",
            lancedb_path=home / "lancedb",
            logs_path=home / "logs",
        )

    def ensure(self) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        self.lancedb_path.mkdir(parents=True, exist_ok=True)
        self.logs_path.mkdir(parents=True, exist_ok=True)
        if not self.config_path.exists():
            self.config_path.write_text(default_config(), encoding="utf-8")


def default_config() -> str:
    return (
        "# OpenMind local configuration\n"
        "\n[provider]\n"
        'name = "dev"\n'
        f'base_url = "{DEFAULT_LMSTUDIO_BASE_URL}"\n'
        'api_token_env = "LM_API_TOKEN"\n'
        "\n[models]\n"
        'chat_model = ""\n'
        f'embedding_model = "{DEFAULT_MODEL_NAME}"\n'
        "\n[indexing]\n"
        "auto_start_after_setup = true\n"
        "background = true\n"
    )


class ProviderSettings(BaseModel):
    name: str = "dev"
    base_url: str = DEFAULT_LMSTUDIO_BASE_URL
    api_token_env: str = "LM_API_TOKEN"


class ModelSettings(BaseModel):
    chat_model: str = ""
    embedding_model: str = DEFAULT_MODEL_NAME


class IndexingSettings(BaseModel):
    auto_start_after_setup: bool = True
    background: bool = True


class OpenMindConfig(BaseModel):
    provider: ProviderSettings = ProviderSettings()
    models: ModelSettings = ModelSettings()
    indexing: IndexingSettings = IndexingSettings()

    @classmethod
    def load(cls, path: Path) -> "OpenMindConfig":
        if not path.exists():
            return cls()
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        return cls(**data)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_toml(), encoding="utf-8")

    def to_toml(self) -> str:
        return (
            "# OpenMind local configuration\n"
            "\n[provider]\n"
            f'name = "{_escape_toml(self.provider.name)}"\n'
            f'base_url = "{_escape_toml(self.provider.base_url)}"\n'
            f'api_token_env = "{_escape_toml(self.provider.api_token_env)}"\n'
            "\n[models]\n"
            f'chat_model = "{_escape_toml(self.models.chat_model)}"\n'
            f'embedding_model = "{_escape_toml(self.models.embedding_model)}"\n'
            "\n[indexing]\n"
            f"auto_start_after_setup = {_toml_bool(self.indexing.auto_start_after_setup)}\n"
            f"background = {_toml_bool(self.indexing.background)}\n"
        )


def _escape_toml(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _toml_bool(value: bool) -> str:
    return "true" if value else "false"
