from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import yaml

from ai_workflow.errors import AppError


def _mapping(value: object, name: str) -> Mapping[object, object]:
    if not isinstance(value, dict):
        raise AppError("config_invalid", f"{name} must be a mapping")
    return value


def _integer(value: object, name: str) -> int:
    if type(value) is not int:
        raise AppError("config_invalid", f"{name} must be an integer")
    return value


def _strings(value: object, name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(
        isinstance(item, str) for item in value
    ):
        raise AppError("config_invalid", f"{name} must be a list of strings")
    return tuple(value)


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
    disabled_nodes: tuple[str, ...]

    def command(self, name: str) -> tuple[str, ...] | None:
        return self.commands.get(name)

    @classmethod
    def load(cls, repo_root: Path) -> "RepositoryConfig":
        path = repo_root / ".ai-workflow.yaml"
        if not path.is_file():
            raise AppError("config_not_found", f"configuration not found: {path}")
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as error:
            raise AppError("config_invalid", "configuration YAML is invalid") from error
        raw = _mapping({} if loaded is None else loaded, "configuration")
        repository = raw.get("repository")
        if repository is None:
            raise AppError("config_invalid", "repository is required")
        raw_commands = raw.get("commands", {})
        if "commands" in raw:
            raw_commands = _mapping(raw_commands, "commands")
        commands: dict[str, tuple[str, ...]] = {}
        for name, value in raw_commands.items():
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise AppError("config_invalid", f"commands.{name} must be a list of strings")
            commands[str(name)] = tuple(value)
        knowledge = raw.get("knowledge", {})
        if "knowledge" in raw:
            knowledge = _mapping(knowledge, "knowledge")
        max_attempts = _integer(raw.get("max_attempts", 3), "max_attempts")
        if max_attempts < 1:
            raise AppError("config_invalid", "max_attempts must be at least 1")
        review_mode = str(raw.get("review_mode", "human"))
        if review_mode not in {"human", "auto_accept"}:
            raise AppError(
                "config_invalid", "review_mode must be human or auto_accept"
            )
        max_knowledge_entries = _integer(
            knowledge.get("max_entries", 8), "knowledge.max_entries"
        )
        if max_knowledge_entries < 1:
            raise AppError(
                "config_invalid", "knowledge.max_entries must be positive"
            )
        max_knowledge_characters = _integer(
            knowledge.get("max_characters", 12000), "knowledge.max_characters"
        )
        if max_knowledge_characters < 1:
            raise AppError(
                "config_invalid", "knowledge.max_characters must be positive"
            )
        return cls(
            repository=str(repository),
            services=_strings(raw.get("services"), "services"),
            wiki_path=(repo_root / raw.get("wiki_path", "wiki")).resolve(),
            commands=commands,
            max_attempts=max_attempts,
            review_mode=review_mode,
            max_knowledge_entries=max_knowledge_entries,
            max_knowledge_characters=max_knowledge_characters,
            protected_paths=_strings(raw.get("protected_paths"), "protected_paths"),
            disabled_nodes=_strings(raw.get("disabled_nodes"), "disabled_nodes"),
        )
