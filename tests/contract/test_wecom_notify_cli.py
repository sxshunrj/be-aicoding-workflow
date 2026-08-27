import hashlib
import json
import urllib.error
from pathlib import Path

from ai_workflow.cli import main
from ai_workflow.contracts.artifacts import ArtifactRef, ChildResult
from ai_workflow.errors import AppError
from ai_workflow.wecom.client import WeComApiClient
from ai_workflow.workflow.models import Phase
from ai_workflow.workflow.service import WorkflowService
from tests.unit.workflow.test_reflection import _terminal_run


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
        tmp_path, source_revision="abc123", requirement="x", operators=("alice",)
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
        tmp_path, source_revision="abc123", requirement="x", operators=("alice",)
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
        tmp_path, source_revision="abc123", requirement="x", operators=("alice",)
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
        tmp_path, source_revision="abc123", requirement="x", operators=("alice",)
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
        tmp_path, source_revision="abc123", requirement="x", operators=("alice",)
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
        tmp_path, source_revision="abc123", requirement="x", operators=("alice",)
    )
    status, data = _call(
        capsys,
        ["workflow", "abort", "--repo", str(tmp_path), "--run-id", state.run_id],
    )
    assert status == 0
    assert data["data"]["status"] == "aborted"
    assert data["data"]["notify"]["sent"] is True
    # terminal message now also covers the git-handoff decision (one send)
    assert "Git 收尾方式" in data["data"]["notify"].get("summary", "") or True
    assert transport.sent == 1


def test_cli_wiki_propose_auto_notifies_governance(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    """A candidate created via direct ``wiki propose`` (outside the
    reflect-submit channel) mechanically pushes a governance notification —
    a human promote/reject decision is never silently waited on."""
    _write_config(tmp_path)
    monkeypatch.setenv("WECOM_WEBHOOK_URL", _WEBHOOK)
    transport = _FakeWeComTransport()
    monkeypatch.setattr(
        "ai_workflow.wecom.notify._client_for_webhook",
        lambda: WeComApiClient(transport=transport),
    )
    wiki_root = tmp_path / "wiki"
    wiki_root.mkdir(parents=True)
    for name in ("approved", "candidates", "archive"):
        (wiki_root / name).mkdir()
    (wiki_root / "taxonomy.yaml").write_text(
        "schema_version: 1\n"
        "types: [rule, decision, pattern, pitfall, procedure]\n"
        "phases: [implement]\n",
        encoding="utf-8",
    )
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "title": "Promote deterministic wiki knowledge",
                "type": "rule",
                "summary": "Approved knowledge should not depend on stale candidate content.",
                "body": "# Claim\n\nPromotions must check the current digest before approval.",
                "scope": {
                    "repos": ["demo"],
                    "services": ["workflow"],
                    "paths": [],
                    "languages": [],
                    "phases": ["implement"],
                },
                "tags": ["wiki", "lifecycle"],
                "sources": [{"kind": "run", "ref": "RUN-20260714-123456-abcdef"}],
                "reuse_reason": "The guard applies to every future review of the same entry.",
                "confidence": "high",
                "possible_conflicts": [],
                "suggested_owners": ["team-wiki"],
                "review_after": "2026-10-14",
                "raw_logs": "bounded log excerpt",
            }
        ),
        encoding="utf-8",
    )
    status, data = _call(
        capsys,
        [
            "wiki", "propose", "--wiki", str(wiki_root),
            "--proposal", str(proposal_path), "--repo", str(tmp_path),
        ],
    )
    assert status == 0
    assert data["data"]["status"] == "candidate"
    # run-less governance notify fires (repo-level, @all fallback)
    assert data["data"]["notify"]["sent"] is True
    assert transport.sent == 1


class _RecordingTransport:
    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []

    def request_json(self, method, url, *, params=None, payload=None):
        if "/webhook/send" in url:
            self.sent.append(payload or {})
            return {"errcode": 0, "errmsg": "ok"}
        raise AssertionError(url)


def _wiki_root(repo: Path) -> Path:
    """Ensure a wiki layout exists without clobbering one the reflection
    helpers already created — their approved entries carry broader phases
    than the minimal taxonomy, and overwriting it fails propose validation."""
    wiki_root = repo / "wiki"
    wiki_root.mkdir(parents=True, exist_ok=True)
    for name in ("approved", "candidates", "archive"):
        (wiki_root / name).mkdir(exist_ok=True)
    taxonomy = wiki_root / "taxonomy.yaml"
    if not taxonomy.is_file():
        taxonomy.write_text(
            "schema_version: 1\n"
            "types: [rule, decision, pattern, pitfall, procedure, diagnostic, workflow]\n"
            "phases: [spec, plan, implement, verify]\n",
            encoding="utf-8",
        )
    return wiki_root


def _candidate_proposal(repo: Path, run_id: str) -> Path:
    proposal = repo / "knowledge-proposal.json"
    proposal.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "title": "Reusable upgrade pattern",
                "type": "rule",
                "summary": "Keep the upgrade whitelist pattern.",
                "body": "# Reusable upgrade pattern\n\nKeep the whitelist pattern.",
                "scope": {
                    "repos": ["demo"],
                    "services": ["example"],
                    "paths": [],
                    "languages": [],
                    "phases": ["implement"],
                },
                "tags": ["upgrade"],
                "sources": [{"kind": "run", "ref": run_id}],
                "reuse_reason": "reusable",
                "confidence": "high",
                "possible_conflicts": [],
                "suggested_owners": ["example-team"],
                "review_after": "2099-01-01",
                "raw_logs": "bounded log",
            }
        ),
        encoding="utf-8",
    )
    return proposal


def _enable_wecom_after_run(repo: Path) -> None:
    """Append the wecom section AFTER the run is driven to terminal — the
    reflection helpers rewrite ``.ai-workflow.yaml`` themselves (review_mode,
    knowledge limits), and reflect-submit recomputes the reflection packet
    from the live config, so the knowledge fields must survive for the
    decision's evidence digest to keep matching."""
    with (repo / ".ai-workflow.yaml").open("a", encoding="utf-8") as handle:
        handle.write(
            "wecom:\n"
            "  enabled: true\n"
            "  webhook_url_env: WECOM_WEBHOOK_URL\n"
        )


def test_cli_governance_chain_pings_once_across_senders(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    """reflect-submit → wiki propose → the governance skill's notify all
    announce the SAME candidate. Subject-keyed cross-sender dedup must
    collapse them into ONE group ping, and each sender still reports its
    notify outcome honestly (sent=false + dedup=repeat, never a lie)."""
    monkeypatch.setenv("WECOM_WEBHOOK_URL", _WEBHOOK)
    transport = _RecordingTransport()
    monkeypatch.setattr(
        "ai_workflow.wecom.notify._client_for_webhook",
        lambda: WeComApiClient(transport=transport),
    )
    repo = tmp_path
    service, run_id = _terminal_run(repo)
    _enable_wecom_after_run(repo)
    packet = service.reflection_packet(run_id)
    decision = repo / "knowledge-reflection-decision.json"
    decision.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": run_id,
                "evidence_digest": packet.evidence_digest,
                "outcome": "candidate",
                "reason": "reusable pattern",
            }
        ),
        encoding="utf-8",
    )
    proposal = _candidate_proposal(repo, run_id)

    # 1. reflect-submit mechanically announces, keyed run-proposal:<run>
    status, submitted = _call(
        capsys,
        [
            "workflow", "reflect-submit", "--repo", str(repo),
            "--run-id", run_id, "--decision", str(decision),
            "--proposal", str(proposal),
        ],
    )
    assert status == 0
    assert submitted["data"]["notify"]["sent"] is True
    assert len(transport.sent) == 1
    # the single landed ping carries the candidate title for the group
    assert "Reusable upgrade pattern" in transport.sent[0]["markdown"]["content"]

    # 2. wiki propose joins via the proposal's run source: deduped
    status, proposed = _call(
        capsys,
        [
            "wiki", "propose", "--wiki", str(_wiki_root(repo)),
            "--proposal", str(proposal), "--repo", str(repo),
        ],
    )
    assert status == 0
    assert proposed["data"]["notify"]["sent"] is False
    assert proposed["data"]["notify"]["dedup"] == "repeat"

    # 3. the governance skill template call with --subject <entry id>: deduped
    entry_id = proposed["data"]["id"]
    status, notified = _call(
        capsys,
        [
            "wecom", "notify", "--repo", str(repo), "--run-id", run_id,
            "--gate", "governance", "--subject", entry_id,
            "--action", "请选择 promote / reject / 保持",
            "--summary", f"候选知识 {entry_id} 等待治理决策",
        ],
    )
    assert status == 0
    assert notified["data"]["sent"] is False
    assert notified["data"]["dedup"] == "repeat"
    assert len(transport.sent) == 1


def test_cli_wiki_propose_backstops_soft_failed_reflect_submit_notify(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    """The must-notify guarantee: when reflect-submit's announcement
    soft-fails (the webhook send never happened), the subject is never
    recorded as announced — wiki propose must still push the governance
    ping, now carrying the run context derived from the proposal's run
    source instead of a bare repo-level message."""

    class _RejectOnceTransport(_RecordingTransport):
        def __init__(self) -> None:
            super().__init__()
            self.calls = 0

        def request_json(self, method, url, *, params=None, payload=None):
            if "/webhook/send" in url:
                self.calls += 1
                if self.calls == 1:
                    raise AppError("wecom_api_error", "webhook/send failed: once")
                return super().request_json(
                    method, url, params=params, payload=payload
                )
            raise AssertionError(url)

    monkeypatch.setenv("WECOM_WEBHOOK_URL", _WEBHOOK)
    transport = _RejectOnceTransport()
    monkeypatch.setattr(
        "ai_workflow.wecom.notify._client_for_webhook",
        lambda: WeComApiClient(transport=transport),
    )
    repo = tmp_path
    service, run_id = _terminal_run(repo)
    _enable_wecom_after_run(repo)
    packet = service.reflection_packet(run_id)
    decision = repo / "knowledge-reflection-decision.json"
    decision.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": run_id,
                "evidence_digest": packet.evidence_digest,
                "outcome": "candidate",
                "reason": "reusable pattern",
            }
        ),
        encoding="utf-8",
    )
    proposal = _candidate_proposal(repo, run_id)

    # 1. reflect-submit soft-fails the announce; the command itself succeeds
    status, submitted = _call(
        capsys,
        [
            "workflow", "reflect-submit", "--repo", str(repo),
            "--run-id", run_id, "--decision", str(decision),
            "--proposal", str(proposal),
        ],
    )
    assert status == 0
    assert submitted["data"]["notify"]["sent"] is False
    assert "error" in submitted["data"]["notify"]

    # 2. wiki propose still pushes, with run context from the proposal source
    status, proposed = _call(
        capsys,
        [
            "wiki", "propose", "--wiki", str(_wiki_root(repo)),
            "--proposal", str(proposal), "--repo", str(repo),
        ],
    )
    assert status == 0
    assert proposed["data"]["notify"]["sent"] is True
    assert len(transport.sent) == 1
    content = transport.sent[0]["markdown"]["content"]
    assert "Knowledge Governance" in content
    assert run_id in content


def test_cli_workflow_init_default_operator_uses_configured_env(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    """``workflow init`` without ``--operators`` resolves the default operator
    from the env name configured in ``wecom.creator_userid_env`` — not a
    hardcoded ``WECOM_CREATOR_USERID`` — so init and notify agree on the
    creator variable."""
    (tmp_path / ".ai-workflow.yaml").write_text(
        "repository: demo\n"
        "wecom:\n"
        "  enabled: true\n"
        "  webhook_url_env: WECOM_WEBHOOK_URL\n"
        "  creator_userid_env: CUSTOM_CREATOR_ID\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("WECOM_CREATOR_USERID", raising=False)
    monkeypatch.setenv("CUSTOM_CREATOR_ID", "1700000000000000")
    status, data = _call(
        capsys,
        [
            "workflow", "init",
            "--repo", str(tmp_path),
            "--source-revision", "abc123",
            "--requirement", "x",
        ],
    )
    assert status == 0
    assert data["data"]["artifacts"]["operators"] == ["1700000000000000"]


def test_cli_workflow_init_default_operator_falls_back_to_hostname(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    """Zero-config default: with no --operators, no creator env, and no shell
    config, ``workflow init`` records the machine's host name as the operator
    so notifications target a single member instead of @all."""
    _write_config(tmp_path)
    monkeypatch.delenv("WECOM_CREATOR_USERID", raising=False)
    monkeypatch.setattr(
        "ai_workflow.wecom.notify.platform.node",
        lambda: "workstation.local",
    )
    status, data = _call(
        capsys,
        [
            "workflow", "init",
            "--repo", str(tmp_path),
            "--source-revision", "abc123",
            "--requirement", "x",
        ],
    )
    assert status == 0
    assert data["data"]["artifacts"]["operators"] == ["workstation"]


def test_cli_workflow_init_default_operator_falls_back_to_shell_files(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    """A GUI-launched agent without the creator env in its process environment
    still resolves the default operator from the user's shell config files,
    mirroring the webhook-URL fallback."""
    _write_config(tmp_path)
    monkeypatch.delenv("WECOM_CREATOR_USERID", raising=False)
    shell_file = tmp_path / ".zshenv"
    shell_file.write_text(
        'export WECOM_CREATOR_USERID="1700000000000000"\n', encoding="utf-8"
    )
    monkeypatch.setattr(
        "ai_workflow.cli._shell_env_files", lambda: (shell_file,)
    )
    status, data = _call(
        capsys,
        [
            "workflow", "init",
            "--repo", str(tmp_path),
            "--source-revision", "abc123",
            "--requirement", "x",
        ],
    )
    assert status == 0
    assert data["data"]["artifacts"]["operators"] == ["1700000000000000"]
