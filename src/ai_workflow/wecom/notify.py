from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Sequence
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
    "terminal": "Terminal Completion",
}

_NOTIFY_DIRNAME = "notifications"


def notification_log_path(repo_root: Path, run_id: str) -> Path:
    return (repo_root / ".ai-workflow" / _NOTIFY_DIRNAME / f"{run_id}.json").resolve()


def reset_notify_dedup(repo_root: Path, run_id: str) -> None:
    """Forget this run's notification history.

    A run that is blocked and then resumed starts a NEW human decision cycle:
    the old dedup digests must not suppress the fresh review/blocked/terminal
    notifications that the new cycle needs. Best-effort — an unreadable or
    unwritable log must never break the resume command.
    """
    try:
        path = notification_log_path(repo_root, run_id)
        if path.is_file():
            path.unlink()
    except OSError:
        pass


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
    creator_raw = operators[0] if operators else "未知"
    creator = "@all" if creator_raw == "@all" else creator_raw
    # WeCom group-robot markdown force-notifies members with <@userid> syntax;
    # plain "@name" is inert text. "@all" is the special group-wide ping and
    # must render as <@all>, not <@@all>.
    mentions = []
    for op in operators:
        if op == "@all":
            mentions.append("<@all>")
        elif op.startswith("<@"):
            mentions.append(op)
        else:
            mentions.append(f"<@{op}>")
    operator_line = " ".join(mentions) if mentions else "@无"
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


def _resolve_operators(
    config: RepositoryConfig, operators: list[str]
) -> list[str]:
    """Ensure the message force-notifies at least one human.

    WeCom group-robot webhooks only force-notify members whose userid appears
    as ``<@userid>`` in the markdown. If a run recorded no operators (init had
    no --operators and no WECOM_CREATOR_USERID), fall back to the configured
    creator userid env, then to ``@all`` so the whole team is pinged — a message
    with "@无" arrives in the group but never surfaces, which users experience
    as "no notification at all".
    """
    resolved = [op for op in operators if isinstance(op, str) and op.strip()]
    if resolved:
        return resolved
    if config.wecom_creator_userid_env:
        value = os.environ.get(config.wecom_creator_userid_env, "").strip()
        if not value:
            value = _env_from_shell_files(
                config.wecom_creator_userid_env, _shell_env_files()
            )
        if value:
            return [value]
    return ["@all"]


def _load_log(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        # A truncated/corrupt/unreadable log means "no prior notifications":
        # never let a broken dedup log block or crash the notify step.
        return {}
    return data if isinstance(data, dict) else {}


def _client_for_webhook() -> WeComApiClient:
    # Webhook messages carry their key in the URL: the client is only a thin
    # holder for the transport.
    return WeComApiClient()


def _shell_env_files() -> tuple[Path, ...]:
    """User-level shell env files that may export the webhook variable.

    Agents launched outside a login shell (GUI apps, services, some IDEs) do
    not inherit a shell's exports, so the process environment can be missing a
    variable that is configured in ``~/.zshenv``. Reading the file directly
    keeps the notify working regardless of how the agent was launched. The
    secret still lives only in the user's own shell config, never in the repo.
    """
    home = Path.home()
    return tuple(
        home / f".{name}"
        for name in ("zshenv", "zshrc", "zprofile", "bash_profile", "profile")
    )


def _env_from_shell_files(name: str, paths: Sequence[Path]) -> str | None:
    """Return the value of ``export NAME=...`` from the first file that sets it."""
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped.startswith("export " + name + "="):
                continue
            value = stripped.split("=", 1)[1].strip()
            if len(value) >= 2 and value[0] in {'"', "'"} and value[-1] == value[0]:
                value = value[1:-1]
            value = value.strip()
            if value:
                return value
    return None


def _webhook_url(config: RepositoryConfig) -> str | None:
    if config.wecom_webhook_url_env is None:
        return None
    value = os.environ.get(config.wecom_webhook_url_env, "").strip()
    if not value:
        value = _env_from_shell_files(
            config.wecom_webhook_url_env, _shell_env_files()
        )
    if not value:
        raise AppError(
            "wecom_not_configured",
            f"WeCom webhook URL is not configured (env {config.wecom_webhook_url_env} missing)",
        )
    return value


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
    webhook_url = _webhook_url(config)
    if webhook_url is None:
        return {"sent": False, "reason": "notify_target_not_configured"}

    service = WorkflowService(repo_root)
    state = service.status(run_id)
    operators = state.artifacts.get("operators", [])
    if not isinstance(operators, list) or not all(
        isinstance(item, str) for item in operators
    ):
        raise AppError("invalid_state", "operators artifact is invalid")
    operators = _resolve_operators(config, operators)

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

    send_client = client if client is not None else _client_for_webhook()
    result = send_client.webhook_send(content=content, webhook_url=webhook_url)

    # A first send is "new"; a resend after content changed is "content_changed";
    # a forced resend of identical content counts as a fresh "new" send.
    dedup = "new" if force or existing is None else "content_changed"
    # The message is already delivered; the dedup log is best-effort bookkeeping.
    # A disk-full / read-only / permission failure here must never crash the
    # enclosing workflow command — notify never blocks the main flow. If the log
    # write fails, the next identical notify will simply re-send (over-notify
    # beats a silent miss), and the failure is surfaced so it stays observable.
    try:
        log[log_key] = digest
        log_path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write: crash mid-write must not corrupt the dedup log.
        temporary = log_path.with_name(f".{log_path.name}.{uuid4().hex}.tmp")
        temporary.write_text(
            json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        temporary.replace(log_path)
    except OSError as error:
        print(
            f"wecom notify dedup-log write failed: {error}",
            file=sys.stderr,
        )
        return {
            "sent": True,
            "dedup": dedup,
            "result": result,
            "webhook": webhook_url,
            "warning": "notify_log_write_failed",
        }
    return {
        "sent": True,
        "dedup": dedup,
        "result": result,
        "webhook": webhook_url,
    }
