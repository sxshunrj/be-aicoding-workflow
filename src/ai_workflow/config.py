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


_WECOM_GATES = ("review", "blocked", "governance", "git_handoff")


def _optional_env_name(value: object, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise AppError("config_invalid", f"{name} must be a non-empty string")
    return value


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
    wecom_enabled: bool = False
    wecom_corpid_env: str | None = None
    wecom_agentid_env: str | None = None
    wecom_agent_secret_env: str | None = None
    wecom_notify_tag: str | None = None
    wecom_creator_userid_env: str | None = None
    wecom_gates: tuple[str, ...] = ("review", "blocked", "governance", "git_handoff")

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
        adapter = raw.get("adapter", {})
        if "adapter" in raw:
            adapter = _mapping(adapter, "adapter")
        wecom = raw.get("wecom", {})
        if "wecom" in raw:
            wecom = _mapping(wecom, "wecom")
        wecom_gates = _strings(wecom.get("gates"), "wecom.gates") or _WECOM_GATES
        for gate in wecom_gates:
            if gate not in _WECOM_GATES:
                raise AppError(
                    "config_invalid",
                    f"wecom.gates contains an unknown gate: {gate}",
                )
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
            wecom_enabled=bool(wecom.get("enabled", False)),
            wecom_corpid_env=_optional_env_name(wecom.get("corpid_env"), "wecom.corpid_env"),
            wecom_agentid_env=_optional_env_name(wecom.get("agentid_env"), "wecom.agentid_env"),
            wecom_agent_secret_env=_optional_env_name(
                wecom.get("agent_secret_env"), "wecom.agent_secret_env"
            ),
            wecom_notify_tag=_optional_env_name(wecom.get("notify_tag"), "wecom.notify_tag"),
            wecom_creator_userid_env=_optional_env_name(
                wecom.get("creator_userid_env"), "wecom.creator_userid_env"
            ),
            wecom_gates=wecom_gates,
        )
