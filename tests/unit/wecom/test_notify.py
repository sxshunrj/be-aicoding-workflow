from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_workflow.config import RepositoryConfig
from ai_workflow.errors import AppError
from ai_workflow.wecom.client import WeComApiClient
from ai_workflow.wecom.notify import notify_command, render_message


class FakeWeComTransport:
    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []
        self.calls: list[tuple[str, str, dict[str, object] | None]] = []

    def request_json(self, method: str, url: str, *, params=None, payload=None) -> dict[str, object]:
        self.calls.append((method, url, payload))
        if url.endswith("/gettoken"):
            return {"errcode": 0, "access_token": "TOK", "expires_in": 7200}
        if url.endswith("/tag/list"):
            return {"errcode": 0, "taglist": [{"tagid": 7, "tagname": "工作流通知组"}]}
        if url.endswith("/message/send"):
            self.sent.append(payload or {})
            return {"errcode": 0, "errmsg": "ok"}
        if "/webhook/send" in url:
            self.sent.append(payload or {})
            return {"errcode": 0, "errmsg": "ok"}
        raise AssertionError(url)


def _config(repo: Path) -> None:
    (repo / ".ai-workflow.yaml").write_text(
        "repository: demo\n"
        "wecom:\n"
        "  enabled: true\n"
        "  corpid_env: WECOM_CORPID\n"
        "  agentid_env: WECOM_AGENT_ID\n"
        "  agent_secret_env: WECOM_AGENT_SECRET\n"
        "  notify_tag: 工作流通知组\n",
        encoding="utf-8",
    )


def _client() -> tuple[WeComApiClient, FakeWeComTransport]:
    transport = FakeWeComTransport()
    return WeComApiClient("corp", "secret", 1000002, transport=transport), transport


def test_render_message_includes_owner_and_operators() -> None:
    content = render_message(
        gate="review",
        phase="plan",
        run_id="RUN-1",
        requirement="实现订单导出",
        repo="demo",
        operators=["sunxianshun", "wangxiaofei"],
        action="接受或修改 rerun",
        summary="plan.solution 已完成",
    )
    assert "🔔 工作流需要人工处理" in content
    assert "👤 开启者：@sunxianshun" in content
    assert "🔑 授权操作者：@sunxianshun @wangxiaofei" in content
    assert "Review Gate（plan 阶段）" in content
    assert "RUN-1" in content
    assert "接受或修改 rerun" in content
    assert "请勿直接操作本工作流" in content


def test_notify_sends_once_then_dedups(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("WECOM_CORPID", "corp")
    monkeypatch.setenv("WECOM_AGENT_ID", "1000002")
    monkeypatch.setenv("WECOM_AGENT_SECRET", "secret")
    _config(tmp_path)
    repo = tmp_path
    # a minimal run must exist so service.status(run_id) succeeds
    from ai_workflow.workflow.service import WorkflowService

    state = WorkflowService().init(
        repo,
        source_revision="abc123",
        requirement="实现订单导出",
        operators=("sunxianshun", "wangxiaofei"),
    )
    run_id = state.run_id
    client, transport = _client()

    first = notify_command(
        repo,
        run_id=run_id,
        gate="review",
        phase="plan",
        action="接受或修改 rerun",
        summary="plan.solution 已完成",
        client=client,
    )
    assert first["sent"] is True
    assert first["dedup"] == "new"

    second = notify_command(
        repo,
        run_id=run_id,
        gate="review",
        phase="plan",
        action="接受或修改 rerun",
        summary="plan.solution 已完成",
        client=client,
    )
    assert second["sent"] is False
    assert second["dedup"] == "repeat"

    third = notify_command(
        repo,
        run_id=run_id,
        gate="review",
        phase="plan",
        action="修改了 rerun 内容",
        summary="plan.solution 已更新",
        client=client,
    )
    assert third["sent"] is True
    assert third["dedup"] == "content_changed"

    assert len(transport.sent) == 2


def test_notify_dry_run_does_not_send(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("WECOM_CORPID", "corp")
    monkeypatch.setenv("WECOM_AGENT_ID", "1000002")
    monkeypatch.setenv("WECOM_AGENT_SECRET", "secret")
    _config(tmp_path)
    repo = tmp_path
    # a minimal run must exist so service.status(run_id) succeeds
    from ai_workflow.workflow.service import WorkflowService

    state = WorkflowService().init(repo, source_revision="abc123", requirement="x")
    run_id = state.run_id
    client, transport = _client()

    result = notify_command(
        repo,
        run_id=run_id,
        gate="blocked",
        phase="implement",
        action="resume 或 abort",
        summary="环境失败",
        client=client,
        dry_run=True,
    )
    assert result["sent"] is False
    assert result["dry_run"] is True
    assert transport.sent == []


def test_notify_noop_when_disabled(tmp_path: Path) -> None:
    (tmp_path / ".ai-workflow.yaml").write_text(
        "repository: demo\n", encoding="utf-8"
    )
    repo = tmp_path
    client, _ = _client()
    result = notify_command(
        repo,
        run_id="RUN-1",
        gate="review",
        action="x",
        client=client,
    )
    assert result["sent"] is False
    assert result["reason"] == "not_enabled"


def test_notify_gate_not_configured_is_noop(tmp_path: Path) -> None:
    (tmp_path / ".ai-workflow.yaml").write_text(
        "repository: demo\n"
        "wecom:\n"
        "  enabled: true\n"
        "  gates: [review]\n",
        encoding="utf-8",
    )
    repo = tmp_path
    client, _ = _client()
    result = notify_command(
        repo,
        run_id="RUN-1",
        gate="blocked",
        action="x",
        client=client,
    )
    assert result["sent"] is False
    assert result["reason"] == "gate_not_configured"


def test_notify_force_resends_identical_content(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("WECOM_CORPID", "corp")
    monkeypatch.setenv("WECOM_AGENT_ID", "1000002")
    monkeypatch.setenv("WECOM_AGENT_SECRET", "secret")
    _config(tmp_path)
    repo = tmp_path
    from ai_workflow.workflow.service import WorkflowService

    state = WorkflowService().init(
        repo, source_revision="abc123", requirement="实现订单导出"
    )
    run_id = state.run_id
    client, transport = _client()

    first = notify_command(
        repo,
        run_id=run_id,
        gate="review",
        phase="plan",
        action="接受或修改 rerun",
        client=client,
    )
    assert first["sent"] is True
    assert first["dedup"] == "new"

    # identical content without --force is deduped
    repeat = notify_command(
        repo,
        run_id=run_id,
        gate="review",
        phase="plan",
        action="接受或修改 rerun",
        client=client,
    )
    assert repeat["sent"] is False
    assert repeat["dedup"] == "repeat"

    # --force bypasses dedup and resends the identical content
    forced = notify_command(
        repo,
        run_id=run_id,
        gate="review",
        phase="plan",
        action="接受或修改 rerun",
        client=client,
        force=True,
    )
    assert forced["sent"] is True
    assert forced["dedup"] == "new"
    assert len(transport.sent) == 2


def test_notify_corrupt_log_does_not_crash(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("WECOM_CORPID", "corp")
    monkeypatch.setenv("WECOM_AGENT_ID", "1000002")
    monkeypatch.setenv("WECOM_AGENT_SECRET", "secret")
    _config(tmp_path)
    repo = tmp_path
    from ai_workflow.wecom.notify import notification_log_path
    from ai_workflow.workflow.service import WorkflowService

    state = WorkflowService().init(
        repo, source_revision="abc123", requirement="实现订单导出"
    )
    run_id = state.run_id
    client, transport = _client()
    # Simulate a truncated/corrupt dedup log: it must be treated as "no prior
    # notifications", not crash the notify step.
    log_path = notification_log_path(repo, run_id)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text('{"review:plan": "this is not a sha256 dig', encoding="utf-8")

    result = notify_command(
        repo,
        run_id=run_id,
        gate="review",
        phase="plan",
        action="接受或修改 rerun",
        client=client,
    )
    assert result["sent"] is True
    assert result["dedup"] == "new"
    assert len(transport.sent) == 1
    # the log is rewritten to valid JSON after a successful send
    assert json.loads(log_path.read_text(encoding="utf-8"))["review:plan"]


def _config_user(repo: Path) -> None:
    (repo / ".ai-workflow.yaml").write_text(
        "repository: demo\n"
        "wecom:\n"
        "  enabled: true\n"
        "  corpid_env: WECOM_CORPID\n"
        "  agentid_env: WECOM_AGENT_ID\n"
        "  agent_secret_env: WECOM_AGENT_SECRET\n"
        "  notify_user: sunxianshun\n",
        encoding="utf-8",
    )


def test_notify_sends_to_user_when_notify_user_configured(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("WECOM_CORPID", "corp")
    monkeypatch.setenv("WECOM_AGENT_ID", "1000002")
    monkeypatch.setenv("WECOM_AGENT_SECRET", "secret")
    _config_user(tmp_path)
    repo = tmp_path
    from ai_workflow.workflow.service import WorkflowService

    state = WorkflowService().init(
        repo, source_revision="abc123", requirement="实现订单导出"
    )
    run_id = state.run_id
    client, transport = _client()

    result = notify_command(
        repo,
        run_id=run_id,
        gate="review",
        phase="plan",
        action="接受或修改 rerun",
        client=client,
    )
    assert result["sent"] is True
    assert result["dedup"] == "new"
    assert result["to_user"] == "sunxianshun"
    # the message/send payload targets touser, not totag
    assert transport.sent[0]["touser"] == "sunxianshun"
    assert "totag" not in transport.sent[0]


def test_notify_requires_a_target(tmp_path: Path) -> None:
    (tmp_path / ".ai-workflow.yaml").write_text(
        "repository: demo\n"
        "wecom:\n"
        "  enabled: true\n"
        "  corpid_env: WECOM_CORPID\n"
        "  agentid_env: WECOM_AGENT_ID\n"
        "  agent_secret_env: WECOM_AGENT_SECRET\n",
        encoding="utf-8",
    )
    repo = tmp_path
    from ai_workflow.workflow.service import WorkflowService

    state = WorkflowService().init(repo, source_revision="abc123", requirement="x")
    client, _ = _client()
    result = notify_command(
        repo,
        run_id=state.run_id,
        gate="review",
        action="x",
        client=client,
    )
    assert result["sent"] is False
    assert result["reason"] == "notify_target_not_configured"


def test_notify_rejects_both_targets(tmp_path: Path) -> None:
    (tmp_path / ".ai-workflow.yaml").write_text(
        "repository: demo\n"
        "wecom:\n"
        "  enabled: true\n"
        "  corpid_env: WECOM_CORPID\n"
        "  agentid_env: WECOM_AGENT_ID\n"
        "  agent_secret_env: WECOM_AGENT_SECRET\n"
        "  notify_tag: 工作流通知组\n"
        "  notify_user: sunxianshun\n",
        encoding="utf-8",
    )
    repo = tmp_path
    from ai_workflow.workflow.service import WorkflowService

    state = WorkflowService().init(repo, source_revision="abc123", requirement="x")
    client, _ = _client()
    result = notify_command(
        repo,
        run_id=state.run_id,
        gate="review",
        action="x",
        client=client,
    )
    assert result["sent"] is False
    assert result["reason"] == "notify_target_ambiguous"


def _config_webhook(repo: Path) -> None:
    (repo / ".ai-workflow.yaml").write_text(
        "repository: demo\n"
        "wecom:\n"
        "  enabled: true\n"
        "  webhook_url_env: WECOM_WEBHOOK_URL\n",
        encoding="utf-8",
    )


def test_notify_sends_to_webhook_without_credentials(tmp_path: Path, monkeypatch) -> None:
    # Webhook target needs NO corpid/secret: it must work without WECOM_* creds.
    monkeypatch.setenv(
        "WECOM_WEBHOOK_URL",
        "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc123",
    )
    _config_webhook(tmp_path)
    repo = tmp_path
    from ai_workflow.workflow.service import WorkflowService

    state = WorkflowService().init(repo, source_revision="abc123", requirement="x")
    run_id = state.run_id
    client, transport = _client()

    result = notify_command(
        repo,
        run_id=run_id,
        gate="review",
        phase="plan",
        action="接受或修改 rerun",
        client=client,
    )
    assert result["sent"] is True
    assert result["dedup"] == "new"
    assert "webhook/send" in result["webhook"]
    # webhook payload has no totag/touser and no agentid
    payload = transport.sent[0]
    assert payload["msgtype"] == "markdown"
    assert "totag" not in payload
    assert "touser" not in payload
    assert "agentid" not in payload


def test_notify_webhook_via_default_client(monkeypatch, tmp_path: Path, capsys) -> None:
    # E2E-ish: real CLI path, no WECOM_CORPID/SECRET set, only webhook URL.
    monkeypatch.setenv(
        "WECOM_WEBHOOK_URL",
        "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc123",
    )
    _config_webhook(tmp_path)
    from ai_workflow.cli import main
    from ai_workflow.wecom.client import WeComApiClient

    transport = FakeWeComTransport()
    monkeypatch.setattr(
        "ai_workflow.wecom.notify._client_for_webhook",
        lambda: WeComApiClient("", "", 0, transport=transport),
    )
    from ai_workflow.workflow.service import WorkflowService

    state = WorkflowService().init(tmp_path, source_revision="abc123", requirement="x")
    status, out = main(
        [
            "wecom",
            "notify",
            "--repo",
            str(tmp_path),
            "--run-id",
            state.run_id,
            "--gate",
            "review",
            "--phase",
            "plan",
            "--action",
            "x",
        ]
    ), capsys.readouterr().out
    assert status == 0
    assert json.loads(out)["data"]["sent"] is True
    assert transport.sent
