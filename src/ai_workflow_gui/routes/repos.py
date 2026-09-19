from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import subprocess

from fastapi import APIRouter, Request
from pydantic import BaseModel

from ai_workflow.config import RepositoryConfig
from ai_workflow.errors import AppError

from ai_workflow_gui._deps import config_path, current_config, find_repo, repo_dir
from ai_workflow_gui.config_store import GuiConfig, RepoEntry, repo_id, save_config

router = APIRouter(prefix="/api/repos", tags=["repos"])
settings_router = APIRouter(prefix="/api/settings", tags=["repos"])


class RegisterBody(BaseModel):
    path: str


class SettingsBody(BaseModel):
    reviewer: str


def config_data(config: RepositoryConfig) -> dict[str, object]:
    data = asdict(config)
    data["wiki_path"] = str(config.wiki_path)
    return data


def git_head(repo_root: Path) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip() or None


@router.get("")
def list_repos(request: Request):
    config = current_config(request)
    return {
        "repos": [entry.to_dict() for entry in config.repos],
        "reviewer": config.reviewer,
    }


@router.post("", status_code=201)
def register_repo(body: RegisterBody, request: Request):
    path = Path(body.path).expanduser().resolve()
    RepositoryConfig.load(path)
    entry = RepoEntry(id=repo_id(path), name=path.name, path=str(path))
    config = current_config(request)
    if any(item.id == entry.id for item in config.repos):
        return entry.to_dict()
    save_config(GuiConfig(config.repos + (entry,), config.reviewer), config_path(request))
    return entry.to_dict()


@router.delete("/{repo_id_value}")
def remove_repo(repo_id_value: str, request: Request):
    config = current_config(request)
    find_repo(config, repo_id_value)
    remaining = tuple(item for item in config.repos if item.id != repo_id_value)
    save_config(GuiConfig(remaining, config.reviewer), config_path(request))
    return {"removed": repo_id_value}


@router.get("/{repo_id_value}")
def repo_detail(repo_id_value: str, request: Request):
    entry = find_repo(current_config(request), repo_id_value)
    return {
        "repo": entry.to_dict(),
        "config": config_data(RepositoryConfig.load(repo_dir(entry))),
    }


@router.get("/{repo_id_value}/head")
def repo_head(repo_id_value: str, request: Request):
    entry = find_repo(current_config(request), repo_id_value)
    return {"head": git_head(repo_dir(entry))}


def _git(repo_root: Path, *args: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout


@router.get("/{repo_id_value}/git-status")
def repo_git_status(repo_id_value: str, request: Request):
    entry = find_repo(current_config(request), repo_id_value)
    root = repo_dir(entry)
    status = _git(root, "status", "--porcelain=v1", "-uno")
    if status is None:
        raise AppError("invalid_arguments", "git status failed (not a git repository?)")
    tracked_noise = {
        name
        for name in ("uv.lock", ".DS_Store")
        if (root / name).exists()
    }
    if tracked_noise:
        keep = [
            line
            for line in status.splitlines()
            if not any(line.endswith(name) for name in tracked_noise)
        ]
        status = "\n".join(keep) + ("\n" if keep else "")
    stat = _git(root, "diff", "--stat", "HEAD") or ""
    return {"status": status, "stat": stat}


@router.get("/{repo_id_value}/git-diff")
def repo_git_diff(repo_id_value: str, request: Request):
    entry = find_repo(current_config(request), repo_id_value)
    diff = _git(repo_dir(entry), "diff", "HEAD")
    if diff is None:
        raise AppError("invalid_arguments", "git diff failed (not a git repository?)")
    return {"diff": diff[-400_000:]}


@settings_router.put("")
def update_settings(body: SettingsBody, request: Request):
    config = current_config(request)
    reviewer = body.reviewer.strip()
    if not reviewer:
        raise AppError("invalid_arguments", "reviewer must not be empty")
    save_config(GuiConfig(config.repos, reviewer), config_path(request))
    return {"reviewer": reviewer}
