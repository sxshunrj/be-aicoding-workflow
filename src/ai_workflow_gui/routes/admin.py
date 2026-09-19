from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from pydantic import BaseModel

from ai_workflow.doctor import run_doctor
from ai_workflow.errors import AppError
from ai_workflow.install import install_skills

from ai_workflow_gui._deps import (
    current_config,
    discover_source_root,
    find_repo,
    repo_dir,
    resolve_clients,
)

router = APIRouter(prefix="/api", tags=["admin"])


class InstallBody(BaseModel):
    client: str = "all"
    scope: str = "user"
    mode: str = "auto"
    repo: str | None = None
    source_root: str | None = None


def home_dir(request: Request) -> Path:
    return Path(request.app.state.home)


def _resolve_source_root(request: Request, override: str | None) -> Path:
    if override:
        candidate = Path(override).expanduser().resolve()
        if not candidate.is_dir():
            raise AppError(
                "invalid_arguments", f"skills source not found: {candidate}"
            )
        return candidate
    discovered = discover_source_root(current_config(request))
    if discovered is None:
        raise AppError(
            "invalid_arguments",
            "skills source not found; register the ai-workflow repository "
            "or pass source_root explicitly",
        )
    return discovered


def registered_repo(request: Request, repo_id_value: str) -> Path:
    return repo_dir(find_repo(current_config(request), repo_id_value))


@router.get("/doctor")
def doctor(
    request: Request,
    repo: str | None = None,
    client: str = "all",
    source_root: str | None = None,
):
    repo_path = registered_repo(request, repo) if repo else None
    report = run_doctor(
        source_root=_resolve_source_root(request, source_root),
        home=home_dir(request),
        repo=repo_path,
        clients=resolve_clients(client),
    )
    return {"ok": not report.failed, "data": report.to_dict()}


@router.post("/install")
def install(body: InstallBody, request: Request):
    if body.mode not in {"auto", "link", "copy"}:
        raise AppError("invalid_arguments", "mode must be auto, link, or copy")
    if body.scope not in {"user", "repo"}:
        raise AppError("invalid_arguments", "scope must be user or repo")
    repo_path = None
    if body.scope == "repo":
        if not body.repo:
            raise AppError("invalid_arguments", "repo is required for repo scope")
        repo_path = registered_repo(request, body.repo)
    report = install_skills(
        source_root=_resolve_source_root(request, body.source_root),
        home=home_dir(request),
        clients=resolve_clients(body.client),
        mode=body.mode,
        scope=body.scope,
        repo=repo_path,
    )
    return {"ok": not report.failed, "data": report.to_dict()}
