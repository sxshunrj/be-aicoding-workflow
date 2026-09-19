from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from pydantic import BaseModel

from ai_workflow.errors import AppError
from ai_workflow.wiki.models import KnowledgeEntry
from ai_workflow.wiki.repository import WikiRepository
from ai_workflow.wiki.service import WikiService

from ai_workflow_gui._deps import (
    current_config,
    file_digest,
    find_repo,
    repo_dir,
    repository_config,
    require_reviewer,
)

router = APIRouter(prefix="/api/repos/{repo_id_value}/wiki", tags=["knowledge"])


class PromoteBody(BaseModel):
    expected_digest: str


class DecisionBody(BaseModel):
    reason: str
    expected_digest: str


def wiki_root(request: Request, repo_id_value: str) -> Path:
    entry = find_repo(current_config(request), repo_id_value)
    return repository_config(repo_dir(entry)).wiki_path


def make_service(root: Path) -> WikiService:
    return WikiService(WikiRepository(root, validate_layout=False))


def entry_summary(entry: KnowledgeEntry, repository: WikiRepository) -> dict[str, object]:
    path = repository.root / "candidates" / f"{entry.id}.md"
    return {
        "id": entry.id,
        "title": entry.title,
        "type": entry.type.value,
        "status": entry.status.value,
        "summary": entry.summary,
        "tags": list(entry.tags),
        "created_at": entry.created_at.isoformat(),
        "path": str(path),
        "digest": repository.path_digest(path),
    }


@router.get("/candidates")
def list_candidates(repo_id_value: str, request: Request):
    repository = WikiRepository(wiki_root(request, repo_id_value), validate_layout=False)
    entries = repository.list("candidate")
    return {"candidates": [entry_summary(entry, repository) for entry in entries]}


def _approved_summary(entry: KnowledgeEntry, repository: WikiRepository) -> dict[str, object]:
    path = repository.root / "approved" / f"{entry.id}.md"
    return {
        "id": entry.id,
        "title": entry.title,
        "type": entry.type.value,
        "status": entry.status.value,
        "summary": entry.summary,
        "tags": list(entry.tags),
        "created_at": entry.created_at.isoformat(),
        "reviewed_at": entry.reviewed_at.isoformat() if entry.reviewed_at else None,
        "review_after": entry.review_after.isoformat(),
        "digest": repository.path_digest(path),
    }


@router.get("/approved")
def list_approved(repo_id_value: str, request: Request):
    repository = WikiRepository(wiki_root(request, repo_id_value), validate_layout=False)
    return {"approved": [_approved_summary(entry, repository) for entry in repository.list("approved")]}


@router.get("/approved/{entry_id}")
def approved_detail(entry_id: str, repo_id_value: str, request: Request):
    repository = WikiRepository(wiki_root(request, repo_id_value), validate_layout=False)
    for entry in repository.list("approved"):
        if entry.id == entry_id:
            summary = _approved_summary(entry, repository)
            summary["body"] = entry.body
            summary["path"] = str(repository.root / "approved" / f"{entry.id}.md")
            return summary
    raise AppError("wiki_not_found", f"approved knowledge not found: {entry_id}")


@router.get("/candidates/{entry_id}")
def review_candidate(entry_id: str, repo_id_value: str, request: Request, max_related: int = 8):
    return make_service(wiki_root(request, repo_id_value)).review_candidate(
        entry_id, max_related
    )


@router.post("/candidates/{entry_id}/promote")
def promote(entry_id: str, body: PromoteBody, repo_id_value: str, request: Request):
    reviewer = require_reviewer(current_config(request))
    service = make_service(wiki_root(request, repo_id_value))
    entry = service.promote(entry_id, reviewer, body.expected_digest)
    path = service.repository.root / "approved" / f"{entry.id}.md"
    return {
        "id": entry.id,
        "status": entry.status.value,
        "path": str(path),
        "digest": file_digest(path),
    }


@router.post("/candidates/{entry_id}/reject")
def reject(entry_id: str, body: DecisionBody, repo_id_value: str, request: Request):
    reviewer = require_reviewer(current_config(request))
    return _decide("reject", entry_id, body, repo_id_value, request, reviewer)


@router.post("/candidates/{entry_id}/archive")
def archive(entry_id: str, body: DecisionBody, repo_id_value: str, request: Request):
    reviewer = require_reviewer(current_config(request))
    return _decide("archive", entry_id, body, repo_id_value, request, reviewer)


def _decide(
    action: str,
    entry_id: str,
    body: DecisionBody,
    repo_id_value: str,
    request: Request,
    reviewer: str,
) -> dict[str, object]:
    if not body.reason.strip():
        raise AppError("invalid_arguments", f"{action} reason must not be empty")
    service = make_service(wiki_root(request, repo_id_value))
    if action == "reject":
        path = service.reject(entry_id, reviewer, body.reason, body.expected_digest)
    else:
        path = service.archive(entry_id, reviewer, body.reason, body.expected_digest)
    return {
        "id": entry_id,
        "status": "archived",
        "path": str(path),
        "digest": file_digest(path),
    }
