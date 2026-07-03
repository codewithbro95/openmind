from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


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
        f'embedding_model = "{DEFAULT_MODEL_NAME}"\n'
        'answer_provider = "none"\n'
    )
