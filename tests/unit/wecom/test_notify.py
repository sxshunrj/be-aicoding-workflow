from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_workflow.config import RepositoryConfig
from ai_workflow.errors import AppError
from ai_workflow.wecom.client import WeComApiClient
from ai_workflow.wecom.notify import (
    _env_from_shell_files,
    _fit_bytes,
    _REQUIREMENT_GIST_MAX_BYTES,
    _requirement_gist,
    _resolve_operators,
    _webhook_url,
    _WECOM_MARKDOWN_MAX_BYTES,
    notify_command,
    render_message,
    reset_notify_dedup,
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


def test_render_message_leads_with_mention_and_action() -> None:
    content = render_message(
        gate="review",
        phase="plan",
        run_id="RUN-1",
        requirement="实现订单导出",
        repo="demo",
        operators=["alice", "bob"],
        action="接受或修改 rerun",
        summary="plan.solution 已完成",
    )
    assert "🔔 工作流需要人工处理" in content
    # operators render as WeCom <@userid> mentions for force-notify, and the
    # mention shares the first line with the action so the pinged operator
    # immediately sees what to do
    assert "👉 <@alice> <@bob>：接受或修改 rerun" in content
    assert "Review Gate（plan 阶段）" in content
    assert "📁 demo" in content
    assert "RUN-1" in content
    assert "🏷 实现订单导出" in content
    assert "plan.solution 已完成" in content


def test_render_message_terminal_gate_label() -> None:
    content = render_message(
        gate="terminal",
        phase=None,
        run_id="RUN-1",
        requirement="x",
        repo="demo",
        operators=["alice"],
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
        operators=("alice", "bob"),
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


def test_notify_run_less_sends_with_repo_context(tmp_path: Path, monkeypatch) -> None:
    """Standalone (run-less) flows — direct `wiki propose`, manual git handoff —
    must still reach the team. Without a run, the message degrades to a
    repo-level context (the 🆔 and gist lines are omitted — no placeholder
    run id, no repo-name gist duplicating the 📁 line) instead of
    hard-failing on state_not_found."""
    _set_webhook_env(monkeypatch)
    _config(tmp_path)
    monkeypatch.setattr("ai_workflow.wecom.notify.platform.node", lambda: "")
    repo = tmp_path
    client, transport = _client()

    result = notify_command(
        repo,
        run_id=None,
        gate="governance",
        action="请选择 promote / reject / 保持",
        summary="知识候选 KB-1 已产生",
        client=client,
    )
    assert result["sent"] is True
    assert result["dedup"] == "new"
    payload = transport.sent[0]
    content = payload["markdown"]["content"]
    # run-less message keeps the repo line, falls back to @all ping, and
    # omits the run-id and gist lines entirely
    assert "demo" in content
    assert "<@all>" in content
    assert "🆔" not in content
    assert "🏷" not in content
    assert "知识候选 KB-1 已产生" in content


def test_notify_unknown_run_id_degrades_to_repo_notify(
    tmp_path: Path, monkeypatch
) -> None:
    """A run-id that no longer exists (run cleaned up) must not hard-fail the
    notify: the team still needs the ping, so the message degrades to a
    repo-level notification instead of raising state_not_found."""
    _set_webhook_env(monkeypatch)
    _config(tmp_path)
    monkeypatch.setattr("ai_workflow.wecom.notify.platform.node", lambda: "")
    repo = tmp_path
    client, transport = _client()

    result = notify_command(
        repo,
        run_id="RUN-DOES-NOT-EXIST",
        gate="git_handoff",
        action="请选择 skip / commit / MR",
        client=client,
    )
    assert result["sent"] is True
    content = transport.sent[0]["markdown"]["content"]
    assert "Git Handoff" in content
    assert "<@all>" in content


def test_notify_run_less_dedup_uses_standalone_log(tmp_path: Path, monkeypatch) -> None:
    """Run-less notifications dedup against a standalone log key so repeated
    identical repo-level pings are suppressed without a run context."""
    _set_webhook_env(monkeypatch)
    _config(tmp_path)
    repo = tmp_path
    client, transport = _client()

    first = notify_command(
        repo,
        run_id=None,
        gate="governance",
        action="请选择 promote / reject / 保持",
        summary="知识候选 KB-1 已产生",
        client=client,
    )
    assert first["sent"] is True

    second = notify_command(
        repo,
        run_id=None,
        gate="governance",
        action="请选择 promote / reject / 保持",
        summary="知识候选 KB-1 已产生",
        client=client,
    )
    assert second["sent"] is False
    assert second["dedup"] == "repeat"
    assert len(transport.sent) == 1


def test_notify_subject_dedups_across_senders_regardless_of_content(
    tmp_path: Path, monkeypatch
) -> None:
    """The governance gate has three senders (reflect-submit, wiki propose,
    the governance skill) announcing the SAME candidate with different
    wording and different run contexts. A subject key present in the shared
    log means announced — wording differences must not re-ping the group."""
    _set_webhook_env(monkeypatch)
    _config(tmp_path)
    repo = tmp_path
    client, transport = _client()

    first = notify_command(
        repo,
        run_id=None,
        gate="governance",
        action="请选择 promote / reject / 保持",
        summary="知识候选 KW-1 已产生，需人工选择 promote / reject / 保持",
        subject="KW-1",
        client=client,
    )
    assert first["sent"] is True
    assert first["dedup"] == "new"

    # same subject, different wording and run context: suppressed
    second = notify_command(
        repo,
        run_id="RUN-1",
        gate="governance",
        action="请选择 promote / reject / 保持",
        summary="候选知识 KW-1（pattern）等待治理决策",
        subject="KW-1",
        client=client,
    )
    assert second["sent"] is False
    assert second["dedup"] == "repeat"
    assert len(transport.sent) == 1

    # a different candidate still notifies: subject dedup is per-decision
    other = notify_command(
        repo,
        run_id=None,
        gate="governance",
        action="请选择 promote / reject / 保持",
        summary="知识候选 KW-2 已产生，需人工选择 promote / reject / 保持",
        subject="KW-2",
        client=client,
    )
    assert other["sent"] is True
    assert len(transport.sent) == 2


def test_notify_alias_subject_suppresses_and_records_primary(
    tmp_path: Path, monkeypatch
) -> None:
    """reflect-submit announces before the entry id exists, keyed
    run-proposal:<run>; wiki propose later arrives with the entry id as its
    primary subject and the run-proposal key as an alias. The alias must
    suppress the send AND record the entry id, so the governance skill's
    --subject lookup dedups too. All keys live in one shared cross-run log."""
    _set_webhook_env(monkeypatch)
    _config(tmp_path)
    repo = tmp_path
    client, transport = _client()

    reflect_submit = notify_command(
        repo,
        run_id="RUN-9",
        gate="governance",
        action="请选择 promote / reject / 保持",
        summary="知识候选「demo pattern」已产生，需人工选择 promote / reject / 保持",
        subject="run-proposal:RUN-9",
        client=client,
    )
    assert reflect_submit["sent"] is True

    wiki_propose = notify_command(
        repo,
        run_id="RUN-9",
        gate="governance",
        action="请选择 promote / reject / 保持",
        summary="知识候选 KW-42 已产生，需人工选择 promote / reject / 保持",
        subject="KW-42",
        alias_subjects=("run-proposal:RUN-9",),
        client=client,
    )
    assert wiki_propose["sent"] is False
    assert wiki_propose["dedup"] == "repeat"

    # the governance skill's call: primary subject only, no alias needed
    skill = notify_command(
        repo,
        run_id="RUN-9",
        gate="governance",
        action="请选择 promote / reject / 保持",
        summary="候选知识 KW-42（demo pattern）等待治理决策",
        subject="KW-42",
        client=client,
    )
    assert skill["sent"] is False
    assert len(transport.sent) == 1

    shared_log = json.loads(
        (repo / ".ai-workflow" / "notifications" / "__subjects__.json").read_text(
            encoding="utf-8"
        )
    )
    assert "governance::run-proposal:RUN-9" in shared_log
    assert "governance::KW-42" in shared_log
    # subject announcements never land in a per-run log
    assert not (repo / ".ai-workflow" / "notifications" / "RUN-9.json").exists()


def test_notify_subject_failed_send_stays_announceable(
    tmp_path: Path, monkeypatch
) -> None:
    """The must-notify guarantee: a send that fails (business rejection —
    no retry) must NOT record the subject, so the next sender still pushes
    the announcement instead of being swallowed by a phantom dedup entry."""
    _set_webhook_env(monkeypatch)
    _config(tmp_path)
    repo = tmp_path

    class _RejectingTransport(FakeWeComTransport):
        def request_json(self, method, url, *, params=None, payload=None):
            raise AppError("wecom_api_error", "webhook/send failed: boom")

    failing = WeComApiClient(transport=_RejectingTransport())
    with pytest.raises(AppError):
        notify_command(
            repo,
            gate="governance",
            action="请选择 promote / reject / 保持",
            summary="知识候选 KW-7 已产生",
            subject="KW-7",
            client=failing,
        )
    subjects_log = repo / ".ai-workflow" / "notifications" / "__subjects__.json"
    assert not subjects_log.exists()

    client, transport = _client()
    retried = notify_command(
        repo,
        gate="governance",
        action="请选择 promote / reject / 保持",
        summary="候选知识 KW-7 等待治理决策",
        subject="KW-7",
        client=client,
    )
    assert retried["sent"] is True
    assert len(transport.sent) == 1


def test_reset_notify_dedup_keeps_subject_announcements(
    tmp_path: Path, monkeypatch
) -> None:
    """Resume resets the per-run dedup log (fresh review/blocked/terminal
    cycle) but must NOT re-announce an already-pending candidate decision:
    subject announcements live in the shared log and survive the reset."""
    _set_webhook_env(monkeypatch)
    _config(tmp_path)
    repo = tmp_path
    client, transport = _client()

    first = notify_command(
        repo,
        run_id="RUN-4",
        gate="governance",
        action="请选择 promote / reject / 保持",
        summary="知识候选 KW-5 已产生",
        subject="KW-5",
        client=client,
    )
    assert first["sent"] is True

    reset_notify_dedup(repo, "RUN-4")

    after = notify_command(
        repo,
        run_id="RUN-4",
        gate="governance",
        action="请选择 promote / reject / 保持",
        summary="候选知识 KW-5 等待治理决策",
        subject="KW-5",
        client=client,
    )
    assert after["sent"] is False
    assert after["dedup"] == "repeat"
    assert len(transport.sent) == 1


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
        operators=["1700000000000000", "alice"],
        action="a",
        summary="",
    )
    assert "<@1700000000000000> <@alice>" in content


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
    assert _resolve_operators(config, ["alice"]) == ["alice"]


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
    monkeypatch.setenv("WECOM_CREATOR_USERID", "1700000000000000")
    config = RepositoryConfig.load(tmp_path)
    assert _resolve_operators(config, []) == ["1700000000000000"]


def test_resolve_operators_falls_back_to_at_all(tmp_path: Path, monkeypatch) -> None:
    """Last-resort: no operators, no creator userid, no usable host name ->
    ping the whole group so a human is always force-notified."""
    (tmp_path / ".ai-workflow.yaml").write_text(
        "repository: demo\nwecom:\n  enabled: true\n", encoding="utf-8"
    )
    monkeypatch.setattr("ai_workflow.wecom.notify.platform.node", lambda: "")
    config = RepositoryConfig.load(tmp_path)
    assert _resolve_operators(config, []) == ["@all"]


def test_resolve_operators_falls_back_to_hostname(
    tmp_path: Path, monkeypatch
) -> None:
    """Zero-config default: no operators and no creator userid -> mention the
    machine's host name instead of @all, so a single-member machine gets a
    targeted ping."""
    (tmp_path / ".ai-workflow.yaml").write_text(
        "repository: demo\nwecom:\n  enabled: true\n", encoding="utf-8"
    )
    monkeypatch.setattr(
        "ai_workflow.wecom.notify.platform.node",
        lambda: "workstation.local",
    )
    config = RepositoryConfig.load(tmp_path)
    assert _resolve_operators(config, []) == ["workstation"]


def test_hostname_operator_rejects_unusable_host_names(monkeypatch) -> None:
    """A localized (non-ASCII) or empty host name cannot be a WeCom userid; an
    invalid <@id> silently notifies no one, so @all must stay the fallback."""
    from ai_workflow.wecom.notify import _hostname_operator

    monkeypatch.setattr(
        "ai_workflow.wecom.notify.platform.node", lambda: "张三的MacBook"
    )
    assert _hostname_operator() is None
    monkeypatch.setattr("ai_workflow.wecom.notify.platform.node", lambda: ".local")
    assert _hostname_operator() is None


def test_fit_bytes_keeps_short_text_unchanged() -> None:
    assert _fit_bytes("abc", 100) == "abc"
    assert _fit_bytes("", 100) == ""
    assert _fit_bytes("abc", 0) == ""


def test_fit_bytes_truncates_within_budget_and_never_splits_multibyte() -> None:
    text = "问小通" * 100  # 300 CJK chars = 900 bytes
    result = _fit_bytes(text, 300)
    # the suffix itself costs bytes; result must fit the budget
    assert len(result.encode("utf-8")) <= 300
    # the kept prefix is whole characters, never a split UTF-8 sequence
    assert "�" not in result
    assert result.endswith("（内容过长已截断）")


def test_fit_bytes_tiny_budget_returns_marker() -> None:
    # budget smaller than the marker: still never returns text longer than the
    # marker, and never splits a multibyte character
    result = _fit_bytes("问小通" * 10, 5)
    assert len(result.encode("utf-8")) <= len("…（内容过长已截断）".encode("utf-8"))
    assert "�" not in result


def test_render_message_truncates_oversized_requirement() -> None:
    """A requirement far past WeCom's 4096-byte markdown cap must not flood the
    message: only its title gist is shown (byte-capped), so the whole message
    fits and the API accepts it — otherwise the team never gets the
    notification."""
    requirement = "问小通" * 2000  # 6000 CJK chars = 12000 bytes
    content = render_message(
        gate="review",
        phase="plan",
        run_id="RUN-1",
        requirement=requirement,
        repo="demo",
        operators=["@all"],
        action="等待人工 Review 决定",
        summary="无重跑节点，请验收产物",
    )
    assert len(content.encode("utf-8")) <= _WECOM_MARKDOWN_MAX_BYTES
    assert "（内容过长已截断）" in content
    # the fixed skeleton and the actionable summary survive the truncation
    assert "🔔 工作流需要人工处理" in content
    assert "<@all>" in content
    assert "无重跑节点，请验收产物" in content
    assert "�" not in content


def test_render_message_truncates_oversized_summary() -> None:
    """When the summary (rerun reasons) itself is huge, only a scannable
    excerpt enters the group message — WeCom is a ping, not a report; the
    full text stays in the run state and the agent session."""
    requirement = "短需求"
    summary = "重跑节点 spec.spec\n・spec.spec：" + "问" * 3000
    content = render_message(
        gate="review",
        phase="plan",
        run_id="RUN-1",
        requirement=requirement,
        repo="demo",
        operators=["@all"],
        action="接受或修改重跑方案",
        summary=summary,
    )
    assert len(content.encode("utf-8")) <= _WECOM_MARKDOWN_MAX_BYTES
    # the display excerpt stays well under the API cap
    assert len(content.encode("utf-8")) < 1200
    assert "重跑节点 spec.spec" in content
    assert "（内容过长已截断）" in content
    assert "�" not in content


def test_render_message_summary_is_blank_line_separated_block() -> None:
    """The summary must not blend into the context lines: it renders as its
    own block after a blank line so the human sees what/why at a glance."""
    content = render_message(
        gate="review",
        phase="implement",
        run_id="RUN-1",
        requirement="实现小通语气输出设定",
        repo="jxedt_stars_api",
        operators=["alice"],
        action="接受或修改重跑方案",
        summary="重跑节点 spec.spec\n・spec.spec：重新分析全部固定文案",
    )
    assert "\n\n重跑节点 spec.spec" in content
    # run-less messages keep the separation too
    run_less = render_message(
        gate="governance",
        phase=None,
        run_id=None,
        requirement="",
        repo="demo",
        operators=["@all"],
        action="请选择 promote / reject / 保持",
        summary="知识候选 KW-1 已产生",
    )
    assert "\n\n知识候选 KW-1 已产生" in run_less


def test_review_rounds_sharing_excerpt_still_reping(
    tmp_path: Path, monkeypatch
) -> None:
    """Dedup must digest the FULL summary, not the 360-byte display excerpt:
    two review rounds whose reasons share a long head but differ in the tail
    are different decisions — the second must re-ping instead of being
    swallowed as a repeat of the first."""
    _set_webhook_env(monkeypatch)
    _config(tmp_path)
    repo = tmp_path
    client, transport = _client()
    head = "重新分析全部用户可见固定文案与PRD的符合度并修订P1清单：" + "问" * 150
    first = notify_command(
        repo,
        run_id=None,
        gate="review",
        phase="implement",
        action="接受或修改重跑方案",
        summary=f"重跑节点 spec.spec\n・spec.spec：{head}第一轮尾部",
        client=client,
    )
    assert first["sent"] is True

    second = notify_command(
        repo,
        run_id=None,
        gate="review",
        phase="implement",
        action="接受或修改重跑方案",
        summary=f"重跑节点 spec.spec\n・spec.spec：{head}第二轮尾部",
        client=client,
    )
    assert second["sent"] is True
    assert second["dedup"] == "content_changed"
    # both displays are the same capped excerpt — the ping still went out
    assert len(transport.sent) == 2


def test_auto_notify_review_structures_rerun_summary(
    tmp_path: Path, monkeypatch
) -> None:
    """The review auto-notify front-loads the rerun nodes and states the
    human's actual choice as the action — the group sees what to decide and
    which nodes rerun before any reason text."""
    _set_webhook_env(monkeypatch)
    _config(tmp_path)
    client, transport = _client()
    monkeypatch.setattr(
        "ai_workflow.wecom.notify._client_for_webhook", lambda: client
    )
    from ai_workflow.cli import _auto_notify_review
    from ai_workflow.workflow.review import ReviewDecision

    decision = ReviewDecision.create(
        decision="human_review",
        run_id="RUN-20260827-105621-dfa96e",
        phase="implement",
        state_version=7,
        proposed_reruns=(
            (
                "spec.spec",
                "重新分析全部用户可见固定文案与PRD(docs/features/x.md §4–§7)"
                "的符合度并修订 P1 清单：" + "疑点描述" * 120,
            ),
        ),
        effective_reruns=(),
    )
    result = _auto_notify_review(tmp_path, decision)
    assert result["sent"] is True
    content = transport.sent[0]["markdown"]["content"]
    assert "接受或修改重跑方案" in content
    assert "\n\n重跑节点 spec.spec" in content
    assert "・spec.spec：重新分析" in content
    # the reason work-order is display-capped, never dumped whole
    assert "（内容过长已截断）" in content
    assert len(content.encode("utf-8")) < 1200


def test_render_message_short_content_untouched() -> None:
    content = render_message(
        gate="review",
        phase="plan",
        run_id="RUN-1",
        requirement="实现订单导出",
        repo="demo",
        operators=["alice"],
        action="接受或修改 rerun",
        summary="plan.solution 已完成",
    )
    assert "（内容过长已截断）" not in content
    assert "🏷 实现订单导出" in content
    assert "plan.solution 已完成" in content


def test_requirement_gist_takes_title_line_only() -> None:
    """A pasted PRD is reduced to its title line — the group chat never
    receives the full spec body."""
    prd = (
        "## 功能名称：问小通 · 会话首条「内容由AI生成」标识\n"
        "\n"
        "---"
        "\n"
        "一、功能需求\n"
        "1.1 页面概览\n"
        "问小通回答由生成式 AI 产出，本功能在每次会话的首条 AI 回复上展示标识。\n"
    )
    assert (
        _requirement_gist(prd)
        == "功能名称：问小通 · 会话首条「内容由AI生成」标识"
    )


def test_requirement_gist_prefers_sentence_boundary_cut() -> None:
    """A gist line over the byte budget cuts at its last sentence boundary
    (。！？；) within the budget — a clean sentence ending beats a mid-word
    byte cut like「科一/科四 AI …」."""
    long_line = (
        "实现「小通语气输出设定」需求：PRD 见 docs/features/小通语气输出设定.md。"
        "定义小通（科一 / 科四 AI 助手）的语气人设、口词典与全部固定文案基调。"
        "另含降级兜底文案与红线词表。"
    )
    gist = _requirement_gist(long_line)
    assert gist.endswith("。…（内容过长已截断）")
    assert gist.startswith("实现「小通语气输出设定」需求：PRD 见")
    # no sentence boundary fits the budget → falls back to byte-level cut
    no_boundary = "需" * 200 + "。"
    fallback = _requirement_gist(no_boundary)
    assert "（内容过长已截断）" in fallback
    assert len(fallback.encode("utf-8")) <= _REQUIREMENT_GIST_MAX_BYTES + len(
        "…（内容过长已截断）".encode("utf-8")
    )


def test_requirement_gist_skips_blank_and_separator_lines() -> None:
    assert _requirement_gist("\n\n---\n\n实现订单导出\n详细描述…") == "实现订单导出"
    assert _requirement_gist("# 实现订单导出\n正文") == "实现订单导出"
    assert _requirement_gist("") == ""
    assert _requirement_gist("---\n") == ""


def test_requirement_gist_caps_line_bytes() -> None:
    gist = _requirement_gist("问小通" * 200)
    assert len(gist.encode("utf-8")) <= _REQUIREMENT_GIST_MAX_BYTES
    assert gist.endswith("（内容过长已截断）")


def test_render_message_dumps_no_prd_body_into_group_chat() -> None:
    """End-to-end shape: a full-PRD requirement yields a compact message whose
    gist line is the title only — the body never reaches the group chat."""
    prd = (
        "## 功能名称：问小通 · 会话首条「内容由AI生成」标识\n"
        "---\n"
        "一、功能需求\n"
        "1.1 页面概览：" + "详细规则与表格内容" * 200
    )
    content = render_message(
        gate="review",
        phase="verify",
        run_id="RUN-20260820-105644-224e92",
        requirement=prd,
        repo="jxedt_stars_api",
        operators=["@all"],
        action="run 已 resume，需重新生成 Review 决策",
        summary="旧 Review Gate 已失效（stale），harness 将创建新的 workflow decision",
    )
    assert "🏷 功能名称：问小通 · 会话首条「内容由AI生成」标识" in content
    assert "页面概览" not in content
    assert "详细规则与表格内容" not in content


def test_notify_sends_oversized_requirement_within_wecom_limit(
    tmp_path: Path, monkeypatch
) -> None:
    """End-to-end: a run with an oversized requirement must still send — the
    rendered payload fits WeCom's markdown cap instead of being rejected."""
    _set_webhook_env(monkeypatch)
    _config(tmp_path)
    repo = tmp_path
    from ai_workflow.workflow.service import WorkflowService

    state = WorkflowService().init(
        repo,
        source_revision="abc123",
        requirement="问小通" * 2000,  # 12000 bytes, far over the 4096 cap
        operators=("alice",),
    )
    run_id = state.run_id
    client, transport = _client()

    result = notify_command(
        repo,
        run_id=run_id,
        gate="review",
        phase="plan",
        action="等待人工 Review 决定",
        summary="无重跑节点，请验收产物",
        client=client,
    )
    assert result["sent"] is True
    payload = transport.sent[0]
    content = payload["markdown"]["content"]
    assert len(content.encode("utf-8")) <= _WECOM_MARKDOWN_MAX_BYTES
    assert "（内容过长已截断）" in content
    # dedup log is written after a successful send
    from ai_workflow.wecom.notify import notification_log_path

    log = json.loads(notification_log_path(repo, run_id).read_text(encoding="utf-8"))
    assert "review:plan" in log
