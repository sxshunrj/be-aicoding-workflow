from dataclasses import dataclass
from pathlib import Path

import yaml

from ai_workflow.errors import AppError


@dataclass(frozen=True, slots=True)
class RepositoryConfig:
    repository: str
    services: tuple[str, ...]
    wiki_path: Path
    commands: dict[str, tuple[str, ...]]
    max_attempts: int
    review_mode: str
    max_knowledge_entries: int
    max_knowledge_characters: int
    protected_paths: tuple[str, ...]

    @classmethod
    def load(cls, repo_root: Path) -> "RepositoryConfig":
        path = repo_root / ".ai-workflow.yaml"
        if not path.is_file():
            raise AppError("config_not_found", f"configuration not found: {path}")
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        commands: dict[str, tuple[str, ...]] = {}
        for name, value in (raw.get("commands") or {}).items():
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise AppError("config_invalid", f"commands.{name} must be a list of strings")
            commands[name] = tuple(value)
        knowledge = raw.get("knowledge") or {}
        return cls(
            repository=str(raw["repository"]),
            services=tuple(raw.get("services") or ()),
            wiki_path=(repo_root / raw.get("wiki_path", "wiki")).resolve(),
            commands=commands,
            max_attempts=int(raw.get("max_attempts", 3)),
            review_mode=str(raw.get("review_mode", "human")),
            max_knowledge_entries=int(knowledge.get("max_entries", 8)),
            max_knowledge_characters=int(knowledge.get("max_characters", 12000)),
            protected_paths=tuple(raw.get("protected_paths") or ()),
        )
