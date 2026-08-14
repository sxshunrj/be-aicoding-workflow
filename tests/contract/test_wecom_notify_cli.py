import json
import os
import urllib.error
from pathlib import Path

from ai_workflow.cli import main
from ai_workflow.wecom.client import WeComApiClient
from ai_workflow.workflow.service import WorkflowService


def _write_config(repo: Path) -> None:
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


def test_cli_wecom_notify_dry_run(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setenv("WECOM_CORPID", "corp")
    monkeypatch.setenv("WECOM_AGENT_ID", "1000002")
    monkeypatch.setenv("WECOM_AGENT_SECRET", "secret")
    _write_config(tmp_path)
    state = WorkflowService().init(
        tmp_path, source_revision="abc123", requirement="x", operators=("sunxianshun",)
    )
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
            "接受或修改 rerun",
            "--dry-run",
        ]
    ), capsys.readouterr().out
    assert status == 0
    data = json.loads(out)["data"]
    assert data["sent"] is False
    assert data["dry_run"] is True
    assert "🔔 工作流需要人工处理" in data["payload"]


def test_cli_wecom_notify_not_enabled(tmp_path: Path, capsys) -> None:
    (tmp_path / ".ai-workflow.yaml").write_text("repository: demo\n", encoding="utf-8")
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
            "--action",
            "x",
        ]
    ), capsys.readouterr().out
    assert status == 0
    assert json.loads(out)["data"]["reason"] == "not_enabled"


def test_cli_wecom_notify_network_failure_soft_fails(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    """A network-failing transport must not block the workflow: the CLI returns
    exit 0 with {"ok": true, "data": {"sent": false, "error": ...}}."""
    monkeypatch.setenv("WECOM_CORPID", "corp")
    monkeypatch.setenv("WECOM_AGENT_ID", "1000002")
    monkeypatch.setenv("WECOM_AGENT_SECRET", "secret")
    _write_config(tmp_path)
    state = WorkflowService().init(
        tmp_path, source_revision="abc123", requirement="x", operators=("sunxianshun",)
    )

    # Drive the failure through the real UrllibTransport so the transport's own
    # OSError -> AppError("wecom_http_error") conversion is what soft-fails it.
    def _offline(*args, **kwargs):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr("ai_workflow.wecom.client.urlopen", _offline)
    offline_client = WeComApiClient("corp", "secret", 1000002)
    monkeypatch.setattr(
        "ai_workflow.wecom.notify._default_client", lambda config: offline_client
    )

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
            "接受或修改 rerun",
        ]
    ), capsys.readouterr().out
    assert status == 0
    envelope = json.loads(out)
    assert envelope["ok"] is True
    assert envelope["data"]["sent"] is False
    assert "error" in envelope["data"]


def test_cli_wecom_notify_unset_webhook_surfaces_stderr(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    """An unset webhook URL env var soft-fails without blocking the workflow,
    but the failure reason must be surfaced on stderr so run logs stay
    observable instead of silently swallowing why no message was sent."""
    (tmp_path / ".ai-workflow.yaml").write_text(
        "repository: demo\n"
        "wecom:\n"
        "  enabled: true\n"
        "  webhook_url_env: BE_AI_WORKFLOW_WEBHOOK_URL\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("BE_AI_WORKFLOW_WEBHOOK_URL", raising=False)
    state = WorkflowService().init(
        tmp_path, source_revision="abc123", requirement="x"
    )
    status = main(
        [
            "wecom",
            "notify",
            "--repo",
            str(tmp_path),
            "--run-id",
            state.run_id,
            "--gate",
            "review",
            "--action",
            "x",
        ]
    )
    captured = capsys.readouterr()
    assert status == 0
    envelope = json.loads(captured.out)
    assert envelope["ok"] is True
    assert envelope["data"]["sent"] is False
    assert "wecom_not_configured" in captured.err
    assert "webhook URL is not configured" in captured.err
    assert "webhook URL is not configured" in envelope["data"]["error"]
