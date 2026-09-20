from __future__ import annotations

import json
from pathlib import Path
import time

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ai_workflow.errors import AppError
from ai_workflow.workflow.service import WorkflowService

from ai_workflow_gui._deps import current_config, find_repo, repo_dir
from ai_workflow_gui.agent_runner import DEFAULT_AGENT_COMMAND, build_prompt
from ai_workflow_gui.runlist import list_runs, read_events

router = APIRouter(prefix="/api/repos/{repo_id_value}/runs", tags=["runs"])


class InitBody(BaseModel):
    requirement: str
    profile: str = "full"
    source_revision: str | None = None
    model: str | None = None


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
    state = WorkflowService(root).init(
        root, source_revision, body.requirement, body.profile
    )
    model = (body.model or "").strip()
    if model:
        from dataclasses import replace

        from ai_workflow_gui._deps import config_path
        from ai_workflow_gui.config_store import load_config, save_config

        config = load_config(config_path(request))
        run_models = dict(config.run_models)
        run_models[state.run_id] = model
        save_config(replace(config, run_models=run_models), config_path(request))
    return state.to_dict()


@router.get("/{run_id}")
def run_status(run_id: str, repo_id_value: str, request: Request):
    return service(request, repo_id_value).status(run_id).to_dict()


@router.post("/{run_id}/review-accept")
def review_accept(run_id: str, body: ReviewAcceptBody, repo_id_value: str, request: Request):
    root = repo_root(request, repo_id_value)
    service = WorkflowService(root)
    accepted = service.record_review_acceptance(run_id, body.expected_digest).to_dict()
    auto_resume: dict[str, object]
    try:
        template = (
            current_config(request).agent_command.strip() or DEFAULT_AGENT_COMMAND
        )
        config = current_config(request)
        model = config.run_models.get(run_id, "")
        result = request.app.state.driver.auto_resume(
            run_id=run_id,
            repo_id=repo_id_value,
            repo_root=root,
            state=service.status(run_id),
            template=template,
            model=model,
        )
        if result.get("resumed") is False and result.get("reason") == "already_running":
            request.app.state.driver.schedule_resume(
                run_id=run_id,
                repo_id=repo_id_value,
                repo_root=root,
                template=template,
                model=model,
                get_state=lambda: WorkflowService(root).status(run_id),
            )
            auto_resume = {"resumed": False, "reason": "queued_after_exit"}
        else:
            auto_resume = result
    except AppError as error:
        auto_resume = {"resumed": False, "reason": error.message}
    return {"run": accepted, "auto_resume": auto_resume}


@router.post("/{run_id}/block")
def block_run(run_id: str, body: BlockBody, repo_id_value: str, request: Request):
    if not body.reason.strip():
        raise AppError("invalid_arguments", "reason must not be empty")
    return service(request, repo_id_value).block(run_id, body.reason).to_dict()


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


@router.get("/{run_id}/files")
def run_files(repo_id_value: str, run_id: str, request: Request):
    from ai_workflow_gui.run_files import list_run_files

    return list_run_files(repo_root(request, repo_id_value), run_id)


@router.get("/{run_id}/file")
def run_file(repo_id_value: str, run_id: str, request: Request, path: str):
    from ai_workflow_gui.run_files import read_run_file

    return read_run_file(repo_root(request, repo_id_value), run_id, path)


def _pending_gate(state) -> bool:
    gate = state.artifacts.get("review_gate")
    return (
        isinstance(gate, dict)
        and gate.get("decision") == "human_review"
        and not gate.get("accepted_at")
    )


@router.post("/{run_id}/drive")
def drive_run(run_id: str, repo_id_value: str, request: Request):
    root = repo_root(request, repo_id_value)
    state = WorkflowService(root).status(run_id)
    if state.status in ("completed", "aborted"):
        raise AppError("invalid_arguments", "run 已是终态，无需驱动 agent")
    if _pending_gate(state):
        raise AppError(
            "driver_gate_pending",
            "存在待审批的 review gate：请先在审批 Tab 接受或驳回，再驱动 agent",
        )
    driver = request.app.state.driver
    if driver.is_active(run_id):
        raise AppError("driver_busy", "该 run 的 agent 已在运行中")
    config = current_config(request)
    template = config.agent_command.strip() or DEFAULT_AGENT_COMMAND
    model = config.run_models.get(run_id, "")
    prompt = build_prompt(state.profile, run_id, state.requirement)
    return driver.start(
        run_id=run_id,
        repo_id=repo_id_value,
        repo_root=root,
        template=template,
        prompt=prompt,
        model=model,
    )


@router.get("/{run_id}/drive")
def drive_status(run_id: str, repo_id_value: str, request: Request):
    return request.app.state.driver.status(run_id)


@router.delete("/{run_id}/drive")
def drive_stop(run_id: str, repo_id_value: str, request: Request):
    return request.app.state.driver.stop(run_id)


@router.get("/{run_id}/stream")
def run_stream(run_id: str, repo_id_value: str, request: Request):
    """SSE：1s 推送 run 状态与 driver 状态（仅在变化时发数据帧）。"""
    root = repo_root(request, repo_id_value)
    service = WorkflowService(root)
    driver = request.app.state.driver

    def sse(event: str, data: str) -> str:
        return f"event: {event}\ndata: {data}\n\n"

    def generate():
        last_run: str | None = None
        last_drive_key: tuple | None = None
        ticks = 0
        while True:
            try:
                run_payload = json.dumps(
                    service.status(run_id).to_dict(),
                    ensure_ascii=False,
                    default=str,
                )
            except AppError as error:
                yield sse("fatal", json.dumps({"code": error.code, "message": error.message}))
                return
            if run_payload != last_run:
                last_run = run_payload
                yield sse("run", run_payload)
            drive = driver.status(run_id, tail=200)
            drive_key = (
                drive["state"],
                drive["exit_code"],
                len(drive["tail"]),
                drive["tail"][-1] if drive["tail"] else "",
            )
            if drive_key != last_drive_key:
                last_drive_key = drive_key
                yield sse("drive", json.dumps(drive, ensure_ascii=False))
            ticks += 1
            if ticks % 15 == 0:
                yield ": ping\n\n"
            time.sleep(1.0)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
