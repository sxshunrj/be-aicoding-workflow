from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from pydantic import BaseModel

from ai_workflow.errors import AppError
from ai_workflow.workflow.service import WorkflowService

from ai_workflow_gui._deps import current_config, find_repo, repo_dir
from ai_workflow_gui.runlist import list_runs, read_events

router = APIRouter(prefix="/api/repos/{repo_id_value}/runs", tags=["runs"])


class InitBody(BaseModel):
    requirement: str
    profile: str = "full"
    source_revision: str | None = None


class ReviewAcceptBody(BaseModel):
    expected_digest: str


class BlockBody(BaseModel):
    reason: str


class ResumeBody(BaseModel):
    reruns: dict[str, str] = {}


def repo_root(request: Request, repo_id_value: str) -> Path:
    return repo_dir(find_repo(current_config(request), repo_id_value))


def service(request: Request, repo_id_value: str) -> WorkflowService:
    return WorkflowService(repo_root(request, repo_id_value))


@router.get("")
def list_repo_runs(repo_id_value: str, request: Request):
    return list_runs(repo_root(request, repo_id_value))


@router.post("", status_code=201)
def init_run(body: InitBody, repo_id_value: str, request: Request):
    root = repo_root(request, repo_id_value)
    source_revision = (body.source_revision or "").strip()
    if not source_revision:
        from ai_workflow_gui.routes.repos import git_head

        source_revision = git_head(root) or ""
    if not source_revision:
        raise AppError(
            "invalid_source_revision",
            "source revision is required (repository has no git HEAD)",
        )
    return (
        WorkflowService(root)
        .init(root, source_revision, body.requirement, body.profile)
        .to_dict()
    )


@router.get("/{run_id}")
def run_status(run_id: str, repo_id_value: str, request: Request):
    return service(request, repo_id_value).status(run_id).to_dict()


@router.post("/{run_id}/review-accept")
def review_accept(run_id: str, body: ReviewAcceptBody, repo_id_value: str, request: Request):
    return (
        service(request, repo_id_value)
        .record_review_acceptance(run_id, body.expected_digest)
        .to_dict()
    )


@router.post("/{run_id}/block")
def block_run(run_id: str, body: BlockBody, repo_id_value: str, request: Request):
    if not body.reason.strip():
        raise AppError("invalid_arguments", "reason must not be empty")
    return service(request, repo_id_value).block(run_id, body.reason).to_dict()


@router.post("/{run_id}/repair-review-gate")
def repair_review_gate(run_id: str, repo_id_value: str, request: Request):
    return service(request, repo_id_value).repair_review_gate(run_id).to_dict()


@router.post("/{run_id}/resume")
def resume_run(run_id: str, body: ResumeBody, repo_id_value: str, request: Request):
    for node, reason in body.reruns.items():
        if not node.strip():
            raise AppError("invalid_arguments", "rerun node must not be empty")
        if not reason.strip():
            raise AppError("invalid_arguments", "rerun reason must not be empty")
    return service(request, repo_id_value).resume(run_id, dict(body.reruns)).to_dict()


@router.post("/{run_id}/abort")
def abort_run(run_id: str, repo_id_value: str, request: Request):
    return service(request, repo_id_value).abort(run_id).to_dict()


@router.get("/{run_id}/summary")
def run_summary(run_id: str, repo_id_value: str, request: Request):
    return service(request, repo_id_value).summary(run_id).to_dict()


@router.get("/{run_id}/events")
def run_events(
    run_id: str, repo_id_value: str, request: Request, limit: int = 50
):
    bounded = max(1, min(limit, 500))
    return {"events": read_events(repo_root(request, repo_id_value), run_id, bounded)}
