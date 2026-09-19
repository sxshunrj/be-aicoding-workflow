from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi import Request

from ai_workflow.config import RepositoryConfig
from ai_workflow.errors import AppError

from ai_workflow_gui.config_store import GuiConfig, RepoEntry, load_config


def config_path(request: Request) -> Path:
    return Path(request.app.state.config_path)


def current_config(request: Request) -> GuiConfig:
    return load_config(config_path(request))


def find_repo(config: GuiConfig, repo_id_value: str) -> RepoEntry:
    for entry in config.repos:
        if entry.id == repo_id_value:
            return entry
    raise AppError("repo_not_found", f"repository is not registered: {repo_id_value}")


def repo_dir(entry: RepoEntry) -> Path:
    path = Path(entry.path).expanduser()
    if not path.is_dir():
        raise AppError("repo_not_found", f"repository path no longer exists: {entry.path}")
    return path.resolve()


def require_reviewer(config: GuiConfig) -> str:
    reviewer = config.reviewer.strip()
    if not reviewer:
        raise AppError(
            "invalid_arguments", "reviewer is not configured; set it in GUI settings"
        )
    return reviewer


def resolve_clients(client: str) -> tuple[str, ...]:
    if client not in {"codex", "claude", "all"}:
        raise AppError("invalid_arguments", "client must be codex, claude, or all")
    return ("codex", "claude") if client == "all" else (client,)


def discover_source_root(config: GuiConfig | None = None) -> Path | None:
    import ai_workflow

    packaged = Path(ai_workflow.__file__).resolve().parent / "skills"
    if packaged.is_dir():
        return packaged
    for parent in Path(ai_workflow.__file__).resolve().parents:
        candidate = parent / "skills"
        if candidate.is_dir():
            return candidate.resolve()
    if config is not None:
        for entry in config.repos:
            candidate = Path(entry.path).expanduser() / "skills"
            if candidate.is_dir():
                return candidate.resolve()
    return None


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def repository_config(repo_root: Path) -> RepositoryConfig:
    return RepositoryConfig.load(Path(repo_root).expanduser().resolve())
