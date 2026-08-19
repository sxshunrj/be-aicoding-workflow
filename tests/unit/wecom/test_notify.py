from __future__ import annotations

import json
from pathlib import Path

from ai_workflow.config import RepositoryConfig
from ai_workflow.wecom.client import WeComApiClient
from ai_workflow.wecom.notify import (
    _env_from_shell_files,
    _resolve_operators,
    _webhook_url,
    notify_command,
    render_message,
)


class FakeWeComTransport:
    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []
        self.calls: list[tuple[str, str, dict[str, object] | None]] = []

    def request_json(self, method: str, url: str, *, params=None, payload=None) -> dict[str, object]:
        self.calls.append((method, url, payload))
        if "/webhook/send" in url:
            self.sent.append(payload or {})
            return {"errcode": 0, "errmsg": "ok"}
        raise AssertionError(url)


_WEBHOOK = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc123"


def _config(repo: Path) -> None:
    (repo / ".ai-workflow.yaml").write_text(
        "repository: demo\n"
        "wecom:\n"
        "  enabled: true\n"
        "  webhook_url_env: WECOM_WEBHOOK_URL\n",
        encoding="utf-8",
    )


def _set_webhook_env(monkeypatch) -> None:
    monkeypatch.setenv("WECOM_WEBHOOK_URL", _WEBHOOK)


def _client() -> tuple[WeComApiClient, FakeWeComTransport]:
    transport = FakeWeComTransport()
    return WeComApiClient(transport=transport), transport


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
    # operators now render as WeCom <@userid> mentions for force-notify
    assert "🔑 授权操作者：<@sunxianshun> <@wangxiaofei>" in content
    assert "Review Gate（plan 阶段）" in content
    assert "RUN-1" in content
    assert "接受或修改 rerun" in content
    assert "请勿直接操作本工作流" in content


def test_render_message_terminal_gate_label() -> None:
    content = render_message(
        gate="terminal",
        phase=None,
        run_id="RUN-1",
        requirement="x",
        repo="demo",
        operators=["sunxianshun"],
        action="请验收 run 终态",
        summary="",
    )
    assert "Terminal Completion" in content
    assert "请验收 run 终态" in content


def test_notify_sends_once_then_dedups(tmp_path: Path, monkeypatch) -> None:
    _set_webhook_env(monkeypatch)
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
    _set_webhook_env(monkeypatch)
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
    _set_webhook_env(monkeypatch)
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
    _set_webhook_env(monkeypatch)
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


def test_notify_requires_a_target(tmp_path: Path) -> None:
    (tmp_path / ".ai-workflow.yaml").write_text(
        "repository: demo\n"
        "wecom:\n"
        "  enabled: true\n",
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


def test_notify_sends_to_webhook(tmp_path: Path, monkeypatch) -> None:
    _set_webhook_env(monkeypatch)
    _config(tmp_path)
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
    payload = transport.sent[0]
    assert payload["msgtype"] == "markdown"
    assert payload["markdown"]["content"]


def test_notify_webhook_via_cli(monkeypatch, tmp_path: Path, capsys) -> None:
    # E2E-ish: real CLI path, webhook only — no CorpID/Secret involved.
    _set_webhook_env(monkeypatch)
    _config(tmp_path)
    from ai_workflow.cli import main
    from ai_workflow.wecom.client import WeComApiClient

    transport = FakeWeComTransport()
    monkeypatch.setattr(
        "ai_workflow.wecom.notify._client_for_webhook",
        lambda: WeComApiClient(transport=transport),
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


def test_notify_dedup_log_write_failure_keeps_sent_true_and_warns(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """The message is delivered before the dedup-log write; a write failure
    (disk full / read-only) must not crash the notify step. sent stays true
    because delivery already happened, and the failure is surfaced as a warning
    so an operator knows the dedup log was not updated."""
    from unittest import mock
    from pathlib import Path as _Path

    _set_webhook_env(monkeypatch)
    _config(tmp_path)
    repo = tmp_path
    from ai_workflow.workflow.service import WorkflowService

    state = WorkflowService().init(
        repo, source_revision="abc123", requirement="实现订单导出"
    )
    run_id = state.run_id
    client, transport = _client()

    original_write = _Path.write_text

    def _failing_write(self, *a, **k):
        if "notifications" in str(self):
            raise OSError(28, "No space left on device")
        return original_write(self, *a, **k)

    with mock.patch.object(_Path, "write_text", _failing_write):
        result = notify_command(
            repo,
            run_id=run_id,
            gate="review",
            phase="plan",
            action="接受或修改 rerun",
            client=client,
        )
    captured = capsys.readouterr()
    assert result["sent"] is True
    assert result["dedup"] == "new"
    assert result["warning"] == "notify_log_write_failed"
    assert "notify_log_write_failed" not in captured.out
    assert "dedup-log write failed" in captured.err


def test_notify_unreadable_log_does_not_crash(
    tmp_path: Path, monkeypatch
) -> None:
    """A dedup log that exists but cannot be read must be treated as "no prior
    notifications" — the notify step must not crash on an unreadable file."""
    from unittest import mock
    from pathlib import Path as _Path

    _set_webhook_env(monkeypatch)
    _config(tmp_path)
    repo = tmp_path
    from ai_workflow.wecom.notify import notification_log_path
    from ai_workflow.workflow.service import WorkflowService

    state = WorkflowService().init(
        repo, source_revision="abc123", requirement="实现订单导出"
    )
    run_id = state.run_id
    client, transport = _client()
    log_path = notification_log_path(repo, run_id)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text('{"review:plan": "abc"}', encoding="utf-8")

    original_read = _Path.read_text

    def _failing_read(self, *a, **k):
        if "notifications" in str(self):
            raise OSError(13, "Permission denied")
        return original_read(self, *a, **k)

    with mock.patch.object(_Path, "read_text", _failing_read):
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


def test_env_from_shell_files_parses_export_formats(tmp_path: Path) -> None:
    env_file = tmp_path / "env"
    env_file.write_text(
        "# a comment\n"
        'export WECOM_WEBHOOK_URL="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc"\n'
        "export OTHER_VAR=x\n",
        encoding="utf-8",
    )
    assert (
        _env_from_shell_files("WECOM_WEBHOOK_URL", [env_file])
        == "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc"
    )
    assert _env_from_shell_files("MISSING_VAR", [env_file]) is None


def test_env_from_shell_files_handles_quote_styles_and_equals(tmp_path: Path) -> None:
    env_file = tmp_path / "env"
    env_file.write_text(
        'export A="double quote value"\n'
        "export B='single quote'\n"
        "export C=unquoted-value\n"
        'export D="https://x/?key=a=b=c"\n',
        encoding="utf-8",
    )
    assert _env_from_shell_files("A", [env_file]) == "double quote value"
    assert _env_from_shell_files("B", [env_file]) == "single quote"
    assert _env_from_shell_files("C", [env_file]) == "unquoted-value"
    assert _env_from_shell_files("D", [env_file]) == "https://x/?key=a=b=c"


def test_webhook_url_falls_back_to_shell_file_when_env_missing(
    tmp_path: Path, monkeypatch
) -> None:
    """Agents launched outside a login shell (GUI apps, services) miss the env
    var even though it is exported in ~/.zshenv; the notify must still resolve
    the webhook by reading the shell file directly."""
    (tmp_path / ".ai-workflow.yaml").write_text(
        "repository: demo\n"
        "wecom:\n"
        "  enabled: true\n"
        "  webhook_url_env: BE_AI_WORKFLOW_WECOM_WEBHOOK_URL\n",
        encoding="utf-8",
    )
    env_file = tmp_path / "zshenv"
    env_file.write_text(
        'export BE_AI_WORKFLOW_WECOM_WEBHOOK_URL="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc"\n',
        encoding="utf-8",
    )
    monkeypatch.delenv("BE_AI_WORKFLOW_WECOM_WEBHOOK_URL", raising=False)
    monkeypatch.setattr(
        "ai_workflow.wecom.notify._shell_env_files", lambda: (env_file,)
    )
    config = RepositoryConfig.load(tmp_path)
    assert (
        _webhook_url(config)
        == "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc"
    )


def test_render_message_force_notifies_with_wecom_mention_syntax() -> None:
    """Operators must render as WeCom <@userid> mention syntax so the message
    actually force-notifies the member — plain '@name' is inert text that
    arrives in the group but never surfaces."""
    content = render_message(
        gate="review",
        phase="plan",
        run_id="RUN-1",
        requirement="x",
        repo="demo",
        operators=["1688852707310042", "sunxianshun"],
        action="a",
        summary="",
    )
    assert "<@1688852707310042> <@sunxianshun>" in content
    assert "@1688852707310042" in content  # creator display keeps a plain @


def test_render_message_at_all_is_single_mention() -> None:
    """The @all fallback renders as <@all>, never <@@all>."""
    content = render_message(
        gate="review", phase="plan", run_id="RUN-1", requirement="x",
        repo="demo", operators=["@all"], action="a", summary="",
    )
    assert "<@all>" in content
    assert "<@@all>" not in content


def test_resolve_operators_uses_recorded_operators(tmp_path: Path) -> None:
    """Recorded operators win — no fallback needed."""
    (tmp_path / ".ai-workflow.yaml").write_text(
        "repository: demo\nwecom:\n  enabled: true\n", encoding="utf-8"
    )
    config = RepositoryConfig.load(tmp_path)
    assert _resolve_operators(config, ["sunxianshun"]) == ["sunxianshun"]


def test_resolve_operators_falls_back_to_creator_userid(
    tmp_path: Path, monkeypatch
) -> None:
    """When a run has no operators, fall back to the configured creator userid
    env so the message still force-notifies someone."""
    (tmp_path / ".ai-workflow.yaml").write_text(
        "repository: demo\n"
        "wecom:\n"
        "  enabled: true\n"
        "  creator_userid_env: WECOM_CREATOR_USERID\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("WECOM_CREATOR_USERID", "1688852707310042")
    config = RepositoryConfig.load(tmp_path)
    assert _resolve_operators(config, []) == ["1688852707310042"]


def test_resolve_operators_falls_back_to_at_all(tmp_path: Path) -> None:
    """Last-resort: no operators and no creator userid -> ping the whole group
    so a human is always force-notified."""
    (tmp_path / ".ai-workflow.yaml").write_text(
        "repository: demo\nwecom:\n  enabled: true\n", encoding="utf-8"
    )
    config = RepositoryConfig.load(tmp_path)
    assert _resolve_operators(config, []) == ["@all"]
