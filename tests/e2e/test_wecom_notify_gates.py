from pathlib import Path

from ai_workflow.wecom.client import WeComApiClient
from tests.e2e.fake_agent import CliDriver, FakeAgent


class _FakeWeComTransport:
    def __init__(self) -> None:
        self.sent = 0

    def request_json(self, method, url, *, params=None, payload=None):
        if "/webhook/send" in url:
            self.sent += 1
            return {"errcode": 0, "errmsg": "ok"}
        raise AssertionError(url)


def test_checkpoint_failure_auto_block_notifies(
    tmp_path, project_template, monkeypatch
) -> None:
    """A checkpoint-driven auto-block (inside review-accept) must still push the
    blocked notification even though it bypasses ``workflow block``."""
    project = project_template.copy_to(tmp_path / "notify-repo")
    (project / ".ai-workflow.yaml").write_text(
        "repository: demo\n"
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
    for phase in ("spec", "plan"):
        attempt = app.workflow_begin(run["run_id"], phase)
        for item in attempt["dispatch_plan"]:
            app.workflow_stage(run["run_id"], agent.run(Path(item["packet_file"])))
        app.workflow_finalize(run["run_id"], attempt["attempt_id"])
        app.workflow_review_transition(run["run_id"])

    (project / "src" / "app.py").write_text("preexisting dirty\n", encoding="utf-8")
    implement = app.workflow_begin(run["run_id"], "implement")
    app.workflow_stage(
        run["run_id"], agent.run(Path(implement["dispatch_plan"][0]["packet_file"]))
    )
    app.workflow_finalize(run["run_id"], implement["attempt_id"])
    decision = app.workflow_review(run["run_id"])

    sent_before = transport.sent
    status, payload = app.workflow_review_accept_status(
        run["run_id"], decision["digest"]
    )
    assert status != 0
    assert payload["error"]["code"] == "checkpoint_scope_ambiguous"
    assert app.workflow_status(run["run_id"])["status"] == "blocked"
    # the internal auto-block pushed exactly one blocked notification
    assert transport.sent == sent_before + 1
