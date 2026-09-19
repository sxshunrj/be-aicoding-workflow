from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import tempfile

DEFAULT_CONFIG_PATH = Path.home() / ".ai-workflow-gui" / "config.json"


@dataclass(frozen=True, slots=True)
class RepoEntry:
    id: str
    name: str
    path: str

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id, "name": self.name, "path": self.path}


@dataclass(frozen=True, slots=True)
class GuiConfig:
    repos: tuple[RepoEntry, ...] = ()
    reviewer: str = ""
    agent_command: str = ""


def repo_id(path: str | Path) -> str:
    resolved = str(Path(path).expanduser().resolve())
    return hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:8]


def load_config(path: Path | None = None) -> GuiConfig:
    path = DEFAULT_CONFIG_PATH if path is None else Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return GuiConfig()
    if not isinstance(raw, dict):
        return GuiConfig()
    repos: list[RepoEntry] = []
    items = raw.get("repos")
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            entry_id = item.get("id")
            entry_path = item.get("path")
            if not isinstance(entry_id, str) or not isinstance(entry_path, str):
                continue
            name = item.get("name")
            repos.append(
                RepoEntry(
                    entry_id,
                    name if isinstance(name, str) and name else Path(entry_path).name,
                    entry_path,
                )
            )
    reviewer = raw.get("reviewer")
    agent_command = raw.get("agent_command")
    return GuiConfig(
        tuple(repos),
        reviewer if isinstance(reviewer, str) else "",
        agent_command if isinstance(agent_command, str) else "",
    )


def save_config(config: GuiConfig, path: Path | None = None) -> None:
    path = DEFAULT_CONFIG_PATH if path is None else Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "repos": [entry.to_dict() for entry in config.repos],
        "reviewer": config.reviewer,
        "agent_command": config.agent_command,
    }
    descriptor, temporary = tempfile.mkstemp(
        prefix=".config.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
