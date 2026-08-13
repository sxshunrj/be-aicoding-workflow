from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

from ai_workflow.config import RepositoryConfig
from ai_workflow.errors import AppError
from ai_workflow.wecom.client import WeComApiClient
from ai_workflow.workflow.service import WorkflowService

_GATE_LABELS = {
    "review": "Review Gate",
    "blocked": "Blocked",
    "governance": "Knowledge Governance",
    "git_handoff": "Git Handoff",
}

_NOTIFY_DIRNAME = "notifications"


def notification_log_path(repo_root: Path, run_id: str) -> Path:
    return (repo_root / ".ai-workflow" / _NOTIFY_DIRNAME / f"{run_id}.json").resolve()


def render_message(
    *,
    gate: str,
    phase: str | None,
    run_id: str,
    requirement: str,
    repo: str,
    operators: list[str],
    action: str,
    summary: str,
) -> str:
    label = _GATE_LABELS.get(gate, gate)
    type_line = f"{label}（{phase} 阶段）" if phase else label
    creator = operators[0] if operators else "未知"
    operator_line = " ".join(f"@{op}" for op in operators) or "@无"
    summary_block = f"\n{summary}" if summary else ""
    return (
        "**🔔 工作流需要人工处理**\n\n"
        f"👤 开启者：@{creator}\n"
        f"🔑 授权操作者：{operator_line}\n"
        f"📌 类型：{type_line}\n"
        f"🆔 Run ID：`{run_id}`\n"
        f"🏷 摘要：{requirement}\n"
        f"📁 仓库：{repo}\n"
        f"{summary_block}\n\n"
        f"请授权操作者处理：{action}\n"
        "其他成员仅收到通知，请勿直接操作本工作流。"
    )


def _content_digest(*, gate: str, phase: str | None, content: str) -> str:
    payload = json.dumps(
        {"gate": gate, "phase": phase, "content": content},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _load_log(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        # A truncated/corrupt log means "no prior notifications": never let a
        # broken dedup log block or crash the notify step.
        return {}
    return data if isinstance(data, dict) else {}


def _default_client(config: RepositoryConfig) -> WeComApiClient:
    corpid = os.environ.get(config.wecom_corpid_env or "", "")
    agentid = os.environ.get(config.wecom_agentid_env or "", "")
    corpsecret = os.environ.get(config.wecom_agent_secret_env or "", "")
    if not (corpid and agentid and corpsecret):
        raise AppError(
            "wecom_not_configured",
            "WeCom credentials are not configured in the environment",
        )
    return WeComApiClient(corpid=corpid, corpsecret=corpsecret, agentid=int(agentid))


def notify_command(
    repo_root: Path,
    *,
    run_id: str,
    gate: str,
    action: str,
    summary: str = "",
    phase: str | None = None,
    force: bool = False,
    dry_run: bool = False,
    client: WeComApiClient | None = None,
) -> dict[str, object]:
    if gate not in _GATE_LABELS:
        raise AppError("wecom_invalid_gate", f"unknown gate: {gate}")
    config = RepositoryConfig.load(repo_root)
    if not config.wecom_enabled:
        return {"sent": False, "reason": "not_enabled"}
    if gate not in config.wecom_gates:
        return {"sent": False, "reason": "gate_not_configured"}
    if config.wecom_notify_tag is not None and config.wecom_notify_user is not None:
        return {"sent": False, "reason": "notify_target_ambiguous"}
    if config.wecom_notify_tag is None and config.wecom_notify_user is None:
        return {"sent": False, "reason": "notify_target_not_configured"}

    service = WorkflowService(repo_root)
    state = service.status(run_id)
    operators = state.artifacts.get("operators", [])
    if not isinstance(operators, list) or not all(
        isinstance(item, str) for item in operators
    ):
        raise AppError("invalid_state", "operators artifact is invalid")

    content = render_message(
        gate=gate,
        phase=phase,
        run_id=run_id,
        requirement=state.requirement,
        repo=config.repository,
        operators=operators,
        action=action,
        summary=summary,
    )
    log_path = notification_log_path(repo_root, run_id)
    log = _load_log(log_path)
    # Key the dedup log by gate plus phase so the same gate at different
    # phases (review at plan vs review at verify) never collides.
    log_key = f"{gate}:{phase or ''}"
    existing = log.get(log_key)
    digest = _content_digest(gate=gate, phase=phase, content=content)
    if not force and existing == digest:
        return {"sent": False, "dedup": "repeat", "targets": []}

    if dry_run:
        return {"sent": False, "dry_run": True, "dedup": "new", "payload": content}

    send_client = client if client is not None else _default_client(config)
    if config.wecom_notify_user is not None:
        result = send_client.send_message(
            content=content, msgtype="markdown", to_user=config.wecom_notify_user
        )
        target_key = "to_user"
        target_value = config.wecom_notify_user
    else:
        assert config.wecom_notify_tag is not None
        tag_id = send_client.resolve_tag(config.wecom_notify_tag)
        result = send_client.send_message(
            content=content, msgtype="markdown", tag_id=tag_id
        )
        target_key = "tag_id"
        target_value = tag_id

    log[log_key] = digest
    log_path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic write: crash mid-write must not corrupt the dedup log.
    temporary = log_path.with_name(f".{log_path.name}.{uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(log_path)
    # A first send is "new"; a resend after content changed is "content_changed";
    # a forced resend of identical content counts as a fresh "new" send.
    dedup = "new" if force or existing is None else "content_changed"
    return {
        "sent": True,
        "dedup": dedup,
        "result": result,
        target_key: target_value,
    }
