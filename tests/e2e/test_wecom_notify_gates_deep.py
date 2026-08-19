"""Deep gate-notify tests.

These tests drive the *entire* workflow lifecycle end-to-end and assert the
mechanical notify hooks fire at every gate — review (each phase), terminal
(transition → completed), and blocked — with the per-phase dedup key never
colliding. A silent miss here means a human never learns a run needs them.
"""
from pathlib import Path

from ai_workflow.wecom.client import WeComApiClient
from tests.e2e.fake_agent import CliDriver, FakeAgent


class _FakeWeComTransport:
    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []

    def request_json(self, method, url, *, params=None, payload=None):
        if "/webhook/send" in url:
            self.sent.append(payload or {})
            return {"errcode": 0, "errmsg": "ok"}
        raise AssertionError(url)


def _enable_wecom(project: Path, monkeypatch) -> _FakeWeComTransport:
    (project / ".ai-workflow.yaml").write_text(
        "repository: demo\n"
        "review_mode: human\n"
        "wecom:\n"
        "  enabled: true\n"
        "  webhook_url_env: WECOM_WEBHOOK_URL\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(
        "WECOM_WEBHOOK_URL",
        "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc",
    )
    transport = _FakeWeComTransport()
    monkeypatch.setattr(
        "ai_workflow.wecom.notify._client_for_webhook",
        lambda: WeComApiClient(transport=transport),
    )
    return transport


def _run_phase(
    app: CliDriver, agent: FakeAgent, run_id: str, phase: str
) -> dict[str, object]:
    attempt = app.workflow_begin(run_id, phase)
    for item in attempt["dispatch_plan"]:
        app.workflow_stage(run_id, agent.run(Path(item["packet_file"])))
    app.workflow_finalize(run_id, attempt["attempt_id"])
    return app.workflow_review_transition(run_id)


def test_auto_accept_still_notifies_verify_review_gate(
    tmp_path, project_template, monkeypatch
) -> None:
    """Even with ``review_mode: auto_accept``, the verify gate is always a
    human_review — the final acceptance must never be silently auto-passed and
    therefore never silently un-notified. spec/plan/implement are auto-accepted
    (no notify), verify must notify."""
    project = project_template.copy_to(tmp_path / "auto-accept-repo")
    (project / ".ai-workflow.yaml").write_text(
        "repository: demo\n"
        "review_mode: auto_accept\n"
        "wecom:\n"
        "  enabled: true\n"
        "  webhook_url_env: WECOM_WEBHOOK_URL\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(
        "WECOM_WEBHOOK_URL",
        "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc",
    )
    transport = _FakeWeComTransport()
    monkeypatch.setattr(
        "ai_workflow.wecom.notify._client_for_webhook",
        lambda: WeComApiClient(transport=transport),
    )
    app = CliDriver(project)
    agent = FakeAgent(project)

    run = app.workflow_init(profile="full")
    for phase in ("spec", "plan", "implement", "verify"):
        _run_phase(app, agent, run["run_id"], phase)

    assert app.workflow_status(run["run_id"])["status"] == "completed"
    contents = [p["markdown"]["content"] for p in transport.sent]
    # spec/plan/implement auto-accepted silently; only verify + terminal notify
    assert sum("Review Gate（verify 阶段）" in c for c in contents) == 1
    assert sum("Review Gate（spec 阶段）" in c for c in contents) == 0
    assert sum("Review Gate（plan 阶段）" in c for c in contents) == 0
    assert sum("Review Gate（implement 阶段）" in c for c in contents) == 0
    assert sum("Terminal Completion" in c for c in contents) == 1


def test_block_then_abort_notifies_both_blocked_and_terminal(
    tmp_path, project_template, monkeypatch
) -> None:
    """A blocked run that is aborted instead of resumed must notify twice: once
    for the block decision and once for the terminal abort — the final state is
    aborted, which is its own gate a human must accept."""
    project = project_template.copy_to(tmp_path / "blockabort-repo")
    transport = _enable_wecom(project, monkeypatch)
    app = CliDriver(project)

    run = app.workflow_init(profile="full")

    from ai_workflow.cli import main
    from io import StringIO
    from contextlib import redirect_stdout
    import json

    def _call(argv):
        with redirect_stdout(StringIO()) as out:
            status = main(argv)
        return status, json.loads(out.getvalue())

    status, payload = _call(["workflow", "block", "--repo", str(project),
                             "--run-id", run["run_id"], "--reason", "decided to stop"])
    assert status == 0
    assert payload["data"]["notify"]["sent"] is True

    status, payload = _call(["workflow", "abort", "--repo", str(project),
                             "--run-id", run["run_id"]])
    assert status == 0
    assert payload["data"]["status"] == "aborted"
    assert payload["data"]["notify"]["sent"] is True

    contents = [p["markdown"]["content"] for p in transport.sent]
    assert sum("Blocked" in c for c in contents) == 1
    assert sum("Terminal Completion" in c for c in contents) == 1
    assert len(transport.sent) == 2


def test_governance_and_git_handoff_gates_reach_webhook(
    tmp_path, project_template, monkeypatch
) -> None:
    """The two skill-driven gates — knowledge governance and git handoff — are
    not Helper-mechanical; their SKILL.md templates call ``wecom notify`` and
    depend on that CLI path working. Verify both gate commands actually deliver
    a message to the webhook with the right label."""
    project = project_template.copy_to(tmp_path / "skillgates-repo")
    transport = _enable_wecom(project, monkeypatch)
    app = CliDriver(project)
    run = app.workflow_init(profile="full")

    from ai_workflow.cli import main
    from io import StringIO
    from contextlib import redirect_stdout
    import json

    def _call(argv):
        with redirect_stdout(StringIO()) as out:
            status = main(argv)
        return status, json.loads(out.getvalue())

    status, payload = _call([
        "wecom", "notify", "--repo", str(project), "--run-id", run["run_id"],
        "--gate", "governance", "--action", "请选择 promote / reject / 保持",
    ])
    assert status == 0
    assert payload["data"]["sent"] is True

    status, payload = _call([
        "wecom", "notify", "--repo", str(project), "--run-id", run["run_id"],
        "--gate", "git_handoff", "--action", "请选择 skip / commit / MR",
    ])
    assert status == 0
    assert payload["data"]["sent"] is True

    contents = [p["markdown"]["content"] for p in transport.sent]
    assert sum("Knowledge Governance" in c for c in contents) == 1
    assert sum("Git Handoff" in c for c in contents) == 1


def test_governance_gate_notifies_then_dedups(
    tmp_path, project_template, monkeypatch
) -> None:
    """The governance gate (a real human decision point) notifies once; a repeat
    of the same decision point with identical content dedups instead of spamming
    the team — but the first notification is never skipped."""
    project = project_template.copy_to(tmp_path / "govdedup-repo")
    transport = _enable_wecom(project, monkeypatch)
    app = CliDriver(project)
    run = app.workflow_init(profile="full")

    from ai_workflow.cli import main
    from io import StringIO
    from contextlib import redirect_stdout
    import json

    def _call(argv):
        with redirect_stdout(StringIO()) as out:
            status = main(argv)
        return status, json.loads(out.getvalue())

    argv = [
        "wecom", "notify", "--repo", str(project), "--run-id", run["run_id"],
        "--gate", "governance", "--action", "请选择 promote / reject / 保持",
    ]
    status, payload = _call(argv)
    assert status == 0
    assert payload["data"]["sent"] is True

    status, payload = _call(argv)
    assert status == 0
    assert payload["data"]["sent"] is False
    assert payload["data"]["dedup"] == "repeat"
    assert len(transport.sent) == 1


def test_notify_log_write_failure_does_not_break_block(
    tmp_path, project_template, monkeypatch
) -> None:
    """The message is delivered before the dedup-log write. If that log write
    fails (disk full / read-only dir), the workflow command must still succeed:
    sent stays true (delivery happened) with an observable warning, and the next
    identical notify re-sends — over-notify beats a silent miss."""
    from unittest import mock
    from pathlib import Path as _Path

    project = project_template.copy_to(tmp_path / "logfail-repo")
    _enable_wecom(project, monkeypatch)
    app = CliDriver(project)
    run = app.workflow_init(profile="full")

    original_write = _Path.write_text

    def _failing_write(self, *a, **k):
        if "notifications" in str(self):
            raise OSError(28, "No space left on device")
        return original_write(self, *a, **k)

    from ai_workflow.cli import main
    from io import StringIO
    from contextlib import redirect_stdout
    import json

    with mock.patch.object(_Path, "write_text", _failing_write):
        with redirect_stdout(StringIO()) as out:
            status = main(["workflow", "block", "--repo", str(project),
                           "--run-id", run["run_id"], "--reason", "x"])
    payload = json.loads(out.getvalue())
    assert status == 0
    assert payload["ok"] is True
    assert payload["data"]["status"] == "blocked"
    notify = payload["data"]["notify"]
    assert notify["sent"] is True
    assert notify.get("warning") == "notify_log_write_failed"


def test_full_lifecycle_notifies_review_each_phase_and_terminal(
    tmp_path, project_template, monkeypatch
) -> None:
    """Every gate on the happy path must notify: review at spec/plan/implement/
    verify (human mode) and terminal on transition to completed. The per-phase
    dedup key must never collapse two different gates into one message."""
    project = project_template.copy_to(tmp_path / "full-repo")
    transport = _enable_wecom(project, monkeypatch)
    app = CliDriver(project)
    agent = FakeAgent(project)

    run = app.workflow_init(profile="full")
    for phase in ("spec", "plan", "implement", "verify"):
        _run_phase(app, agent, run["run_id"], phase)

    # verify transition produced the terminal state
    final = app.workflow_status(run["run_id"])
    assert final["status"] == "completed"

    # review gate fired once per phase (4) + terminal completion (1) = 5
    assert len(transport.sent) == 5
    contents = [payload["markdown"]["content"] for payload in transport.sent]
    assert sum("Review Gate（spec 阶段）" in c for c in contents) == 1
    assert sum("Review Gate（plan 阶段）" in c for c in contents) == 1
    assert sum("Review Gate（implement 阶段）" in c for c in contents) == 1
    assert sum("Review Gate（verify 阶段）" in c for c in contents) == 1
    assert sum("Terminal Completion" in c for c in contents) == 1


def test_transition_to_completed_notifies_terminal_once(
    tmp_path, project_template, monkeypatch
) -> None:
    """``workflow transition`` to completed pushes the terminal notification.
    A terminal run cannot be re-transitioned, so a second terminal message is
    structurally impossible — the first transition already notified."""
    project = project_template.copy_to(tmp_path / "terminal-repo")
    transport = _enable_wecom(project, monkeypatch)
    app = CliDriver(project)
    agent = FakeAgent(project)

    run = app.workflow_init(profile="full")
    for phase in ("spec", "plan", "implement", "verify"):
        _run_phase(app, agent, run["run_id"], phase)
    terminal_sends = [p for p in transport.sent
                      if "Terminal Completion" in p["markdown"]["content"]]
    assert len(terminal_sends) == 1

    # re-transitioning a completed run is rejected (terminal run cannot be
    # changed) — and it never sends a second terminal message
    from ai_workflow.cli import main
    import json
    from io import StringIO
    from contextlib import redirect_stdout
    with redirect_stdout(StringIO()) as out:
        status = main(["workflow", "transition", "--repo", str(project),
                       "--run-id", run["run_id"]])
    payload = json.loads(out.getvalue())
    assert status == 2
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_transition"
    terminal_sends = [p for p in transport.sent
                      if "Terminal Completion" in p["markdown"]["content"]]
    assert len(terminal_sends) == 1


def test_block_then_resume_then_block_distinct_reasons_both_notify(
    tmp_path, project_template, monkeypatch
) -> None:
    """A block, resume, then a fresh block with a *different* reason must notify
    again — the dedup key carries the content digest so a new decision point is
    never swallowed. This guards against the historical silent-miss class."""
    project = project_template.copy_to(tmp_path / "reblock-repo")
    transport = _enable_wecom(project, monkeypatch)
    app = CliDriver(project)

    run = app.workflow_init(profile="full")

    from ai_workflow.cli import main
    from io import StringIO
    from contextlib import redirect_stdout
    import json

    def _call(argv):
        with redirect_stdout(StringIO()) as out:
            status = main(argv)
        return status, json.loads(out.getvalue())

    status, payload = _call(["workflow", "block", "--repo", str(project),
                             "--run-id", run["run_id"],
                             "--reason", "waiting on stakeholder"])
    assert status == 0
    assert payload["data"]["notify"]["sent"] is True
    blocked = [p for p in transport.sent
               if "Blocked" in p["markdown"]["content"]]
    assert len(blocked) == 1

    status, payload = _call(["workflow", "resume", "--repo", str(project),
                             "--run-id", run["run_id"]])
    assert status == 0
    assert payload["data"]["status"] == "pending"

    # fresh block with a different reason — must be a NEW notification
    status, payload = _call(["workflow", "block", "--repo", str(project),
                             "--run-id", run["run_id"],
                             "--reason", "blocked again: env down"])
    assert status == 0
    assert payload["data"]["notify"]["sent"] is True
    blocked = [p for p in transport.sent
               if "Blocked" in p["markdown"]["content"]]
    assert len(blocked) == 2


def test_blocked_dedup_same_phase_same_reason_repeats_once(
    tmp_path, project_template, monkeypatch
) -> None:
    """Blocking with the exact same reason at the same phase dedups (no spam),
    but the first block still notified — a human was never left blind."""
    project = project_template.copy_to(tmp_path / "blockdedup-repo")
    transport = _enable_wecom(project, monkeypatch)
    app = CliDriver(project)

    run = app.workflow_init(profile="full")

    from ai_workflow.cli import main
    from io import StringIO
    from contextlib import redirect_stdout
    import json

    def _call(argv):
        with redirect_stdout(StringIO()) as out:
            status = main(argv)
        return status, json.loads(out.getvalue())

    args = ["workflow", "block", "--repo", str(project),
            "--run-id", run["run_id"], "--reason", "same reason"]
    status, payload = _call(args)
    assert status == 0
    assert payload["data"]["notify"]["sent"] is True

    status, payload = _call(args)
    assert status == 0
    assert payload["data"]["status"] == "blocked"
    assert payload["data"]["notify"]["sent"] is False
    assert payload["data"]["notify"]["dedup"] == "repeat"
    blocked = [p for p in transport.sent
               if "Blocked" in p["markdown"]["content"]]
    assert len(blocked) == 1
