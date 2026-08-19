import hashlib
import json
import urllib.error
from pathlib import Path

from ai_workflow.cli import main
from ai_workflow.contracts.artifacts import ArtifactRef, ChildResult
from ai_workflow.wecom.client import WeComApiClient
from ai_workflow.workflow.models import Phase
from ai_workflow.workflow.service import WorkflowService


_WEBHOOK = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc123"


def _write_config(repo: Path) -> None:
    (repo / ".ai-workflow.yaml").write_text(
        "repository: demo\n"
        "wecom:\n"
        "  enabled: true\n"
        "  webhook_url_env: WECOM_WEBHOOK_URL\n",
        encoding="utf-8",
    )


def _skill_dir(root: Path) -> Path:
    path = root / "skill" / "references" / "agents"
    path.mkdir(parents=True)
    for name in ("common-phase-contract.md", "spec-writer.md"):
        (path / name).write_text(f"# {name}\n", encoding="utf-8")
    return path.parents[1]


def _call(capsys, argv: list[str]) -> tuple[int, dict[str, object]]:
    status = main(argv)
    return status, json.loads(capsys.readouterr().out)


def test_cli_wecom_notify_dry_run(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setenv("WECOM_WEBHOOK_URL", _WEBHOOK)
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


def test_cli_wecom_notify_terminal_gate_dry_run(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.setenv("WECOM_WEBHOOK_URL", _WEBHOOK)
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
            "terminal",
            "--action",
            "请验收 run 终态",
            "--dry-run",
        ]
    ), capsys.readouterr().out
    assert status == 0
    data = json.loads(out)["data"]
    assert data["dry_run"] is True
    assert "Terminal Completion" in data["payload"]


def test_cli_wecom_notify_network_failure_soft_fails(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    """A network-failing transport must not block the workflow: the CLI returns
    exit 0 with {"ok": true, "data": {"sent": false, "error": ...}}."""
    monkeypatch.setenv("WECOM_WEBHOOK_URL", _WEBHOOK)
    _write_config(tmp_path)
    state = WorkflowService().init(
        tmp_path, source_revision="abc123", requirement="x", operators=("sunxianshun",)
    )

    # Drive the failure through the real UrllibTransport so the transport's own
    # OSError -> AppError("wecom_http_error") conversion is what soft-fails it.
    def _offline(*args, **kwargs):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr("ai_workflow.wecom.client.urlopen", _offline)

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


class _FakeWeComTransport:
    def __init__(self) -> None:
        self.sent = 0

    def request_json(self, method, url, *, params=None, payload=None):
        if "/webhook/send" in url:
            self.sent += 1
            return {"errcode": 0, "errmsg": "ok"}
        raise AssertionError(url)


def test_cli_workflow_block_auto_notifies_blocked_gate(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    """``workflow block`` mechanically pushes the blocked notification so a
    blocked run is always visible to the team, independent of the harness LLM
    following the skill template."""
    _write_config(tmp_path)
    monkeypatch.setenv("WECOM_WEBHOOK_URL", _WEBHOOK)
    transport = _FakeWeComTransport()
    monkeypatch.setattr(
        "ai_workflow.wecom.notify._client_for_webhook",
        lambda: WeComApiClient(transport=transport),
    )
    state = WorkflowService().init(
        tmp_path, source_revision="abc123", requirement="x", operators=("sunxianshun",)
    )
    status, data = _call(
        capsys,
        [
            "workflow",
            "block",
            "--repo",
            str(tmp_path),
            "--run-id",
            state.run_id,
            "--reason",
            "checkpoint_scope_ambiguous",
        ],
    )
    assert status == 0
    assert data["data"]["notify"]["sent"] is True
    assert transport.sent == 1


def test_cli_workflow_block_auto_notify_soft_fails_without_breaking(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    """A blocked run with WeCom enabled but no webhook env must still block:
    the notify soft-fails to a warning and never breaks the block."""
    _write_config(tmp_path)
    monkeypatch.delenv("WECOM_WEBHOOK_URL", raising=False)
    state = WorkflowService().init(
        tmp_path, source_revision="abc123", requirement="x", operators=("sunxianshun",)
    )
    status = main(
        [
            "workflow",
            "block",
            "--repo",
            str(tmp_path),
            "--run-id",
            state.run_id,
            "--reason",
            "checkpoint_scope_ambiguous",
        ]
    )
    captured = capsys.readouterr()
    assert status == 0
    envelope = json.loads(captured.out)
    assert envelope["ok"] is True
    assert envelope["data"]["status"] == "blocked"
    assert envelope["data"]["notify"]["sent"] is False
    assert envelope["data"]["notify"]["error"] == "wecom_not_configured"
    assert "wecom notify soft-failed" in captured.err


def test_cli_workflow_review_human_review_auto_notifies(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    """``workflow review`` returning human_review mechanically pushes the
    review-gate notification, independent of the harness LLM."""
    _write_config(tmp_path)
    monkeypatch.setenv("WECOM_WEBHOOK_URL", _WEBHOOK)
    transport = _FakeWeComTransport()
    monkeypatch.setattr(
        "ai_workflow.wecom.notify._client_for_webhook",
        lambda: WeComApiClient(transport=transport),
    )
    skill_dir = _skill_dir(tmp_path)
    status, init = _call(
        capsys,
        [
            "workflow", "init", "--repo", str(tmp_path),
            "--source-revision", "abc123", "--requirement", "Specify the change",
        ],
    )
    assert status == 0
    run_id = init["data"]["run_id"]

    status, begin = _call(
        capsys,
        [
            "workflow", "begin", "--repo", str(tmp_path), "--run-id", run_id,
            "--phase", "spec", "--skill-dir", str(skill_dir),
        ],
    )
    assert status == 0
    attempt_id = begin["data"]["attempt_id"]

    artifact_path = tmp_path / "artifacts" / "spec-spec.md"
    artifact_path.parent.mkdir()
    artifact_path.write_text("# Spec\n", encoding="utf-8")
    result_path = tmp_path / "spec-result.json"
    ChildResult(
        run_id=run_id,
        phase=Phase.SPEC,
        child="spec",
        attempt_id=attempt_id,
        execution_mode="fresh",
        status="completed",
        summary="specified",
        artifact=ArtifactRef(
            path="artifacts/spec-spec.md",
            sha256=hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
            schema_version=2,
            phase=Phase.SPEC,
            child="spec",
            source_revision="abc123",
        ),
        findings=(),
    ).write(result_path)

    status, _ = _call(
        capsys,
        [
            "workflow", "stage", "--repo", str(tmp_path), "--run-id", run_id,
            "--attempt-id", attempt_id, "--child", "spec", "--result", str(result_path),
        ],
    )
    assert status == 0
    status, finalized = _call(
        capsys,
        [
            "workflow", "finalize", "--repo", str(tmp_path), "--run-id", run_id,
            "--attempt-id", attempt_id,
        ],
    )
    assert status == 0
    assert finalized["data"]["status"] == "completed"

    status, review = _call(
        capsys, ["workflow", "review", "--repo", str(tmp_path), "--run-id", run_id]
    )
    assert status == 0
    assert review["data"]["decision"] == "human_review"
    assert review["data"]["notify"]["sent"] is True
    assert transport.sent == 1


def test_cli_workflow_abort_auto_notifies_terminal(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    """``workflow abort`` making the run aborted mechanically pushes the
    terminal-completion notification."""
    _write_config(tmp_path)
    monkeypatch.setenv("WECOM_WEBHOOK_URL", _WEBHOOK)
    transport = _FakeWeComTransport()
    monkeypatch.setattr(
        "ai_workflow.wecom.notify._client_for_webhook",
        lambda: WeComApiClient(transport=transport),
    )
    state = WorkflowService().init(
        tmp_path, source_revision="abc123", requirement="x", operators=("sunxianshun",)
    )
    status, data = _call(
        capsys,
        ["workflow", "abort", "--repo", str(tmp_path), "--run-id", state.run_id],
    )
    assert status == 0
    assert data["data"]["status"] == "aborted"
    assert data["data"]["notify"]["sent"] is True
    assert transport.sent == 1
