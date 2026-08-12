import json
import os
from pathlib import Path

from ai_workflow.cli import main
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
