from dataclasses import dataclass
import os
from pathlib import Path
import re
from typing import Mapping

import yaml

from ai_workflow.errors import AppError


SCHEMA_VERSION = 2

_SCHEMA_LINE = re.compile(r"^schema_version\s*:.*$")


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
    adapter_source_paths: tuple[str, ...]
    adapter_test_paths: tuple[str, ...]
    adapter_generated_test_destinations: tuple[str, ...]
    adapter_report_paths: tuple[str, ...]

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
        version = raw.get("schema_version")
        if version != SCHEMA_VERSION:
            raise AppError(
                "unsupported_schema_version",
                f"unsupported repository schema_version: {version!r}; run "
                f"`ai-workflow config migrate --repo <repo>` to upgrade to "
                f"{SCHEMA_VERSION}",
            )
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
        adapter = raw.get("adapter", {})
        if "adapter" in raw:
            adapter = _mapping(adapter, "adapter")
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
            adapter_source_paths=_strings(
                adapter.get("source_paths"), "adapter.source_paths"
            ),
            adapter_test_paths=_strings(
                adapter.get("test_paths"), "adapter.test_paths"
            ),
            adapter_generated_test_destinations=_strings(
                adapter.get("generated_test_destinations"),
                "adapter.generated_test_destinations",
            ),
            adapter_report_paths=_strings(
                adapter.get("report_paths"), "adapter.report_paths"
            ),
        )


@dataclass(frozen=True, slots=True)
class ConfigMigrationResult:
    """Outcome of upgrading one repository configuration file."""

    path: str
    from_version: int
    to_version: int
    changed: bool
    dry_run: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "from_version": self.from_version,
            "to_version": self.to_version,
            "changed": self.changed,
            "dry_run": self.dry_run,
        }


def migrate_repository_config(
    repo_root: Path,
    *,
    to_version: int = SCHEMA_VERSION,
    dry_run: bool = False,
) -> ConfigMigrationResult:
    """Upgrade ``<repo>/.ai-workflow.yaml`` to the current schema version.

    Only the ``schema_version`` line changes: every other key keeps its value,
    comment, and position, because the file belongs to the user. A missing
    version is read as legacy v1. Unknown versions are refused rather than
    guessed at.
    """
    if to_version != SCHEMA_VERSION:
        raise AppError(
            "invalid_arguments",
            f"config migrate only supports --to {SCHEMA_VERSION}",
        )
    path = repo_root / ".ai-workflow.yaml"
    if not path.is_file():
        raise AppError("config_not_found", f"configuration not found: {path}")
    text = path.read_text(encoding="utf-8")
    try:
        loaded = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise AppError("config_invalid", "configuration YAML is invalid") from error
    raw = _mapping({} if loaded is None else loaded, "configuration")
    declared = raw.get("schema_version")
    if declared not in (None, 1, SCHEMA_VERSION) or type(declared) is bool:
        raise AppError(
            "unsupported_schema_version",
            f"unsupported repository schema_version: {declared!r}",
        )
    from_version = 1 if declared is None else declared
    if declared == SCHEMA_VERSION:
        return ConfigMigrationResult(
            str(path), SCHEMA_VERSION, SCHEMA_VERSION, False, dry_run
        )

    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if _SCHEMA_LINE.match(line):
            lines[index] = f"schema_version: {SCHEMA_VERSION}\n"
            break
    else:
        insert_at = next(
            (
                index
                for index, line in enumerate(lines)
                if line.strip() and not line.lstrip().startswith("#")
            ),
            len(lines),
        )
        lines.insert(insert_at, f"schema_version: {SCHEMA_VERSION}\n")
    updated = "".join(lines)
    candidate = yaml.safe_load(updated)
    _mapping({} if candidate is None else candidate, "configuration")
    if not dry_run:
        temporary = path.with_name(f".{path.name}.migrate.tmp")
        temporary.write_text(updated, encoding="utf-8")
        os.replace(temporary, path)
    return ConfigMigrationResult(
        str(path), from_version, SCHEMA_VERSION, True, dry_run
    )
