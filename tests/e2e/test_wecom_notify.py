import json
from pathlib import Path

from ai_workflow.cli import main
from ai_workflow.wecom.client import WeComApiClient
from ai_workflow.workflow.service import WorkflowService


class FakeWeComTransport:
    def __init__(self) -> None:
        self.sent = 0

    def request_json(self, method, url, *, params=None, payload=None):
        if url.endswith("/gettoken"):
            return {"errcode": 0, "access_token": "TOK", "expires_in": 7200}
        if url.endswith("/tag/list"):
            return {"errcode": 0, "taglist": [{"tagid": 7, "tagname": "工作流通知组"}]}
        if url.endswith("/message/send"):
            self.sent += 1
            return {"errcode": 0, "errmsg": "ok"}
        raise AssertionError(url)


def test_wecom_notify_e2e_dedup(monkeypatch, tmp_path: Path, capsys) -> None:
    (tmp_path / ".ai-workflow.yaml").write_text(
        "repository: demo\n"
        "wecom:\n"
        "  enabled: true\n"
        "  corpid_env: WECOM_CORPID\n"
        "  agentid_env: WECOM_AGENT_ID\n"
        "  agent_secret_env: WECOM_AGENT_SECRET\n"
        "  notify_tag: 工作流通知组\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("WECOM_CORPID", "corp")
    monkeypatch.setenv("WECOM_AGENT_ID", "1000002")
    monkeypatch.setenv("WECOM_AGENT_SECRET", "secret")
    transport = FakeWeComTransport()
    monkeypatch.setattr(
        "ai_workflow.wecom.notify._default_client",
        lambda config: WeComApiClient("corp", "secret", 1000002, transport=transport),
    )

    state = WorkflowService().init(
        tmp_path, source_revision="abc123", requirement="实现订单导出",
        operators=("sunxianshun", "wangxiaofei"),
    )
    run_id = state.run_id
    base = [
        "wecom",
        "notify",
        "--repo",
        str(tmp_path),
        "--run-id",
        run_id,
        "--gate",
        "review",
        "--phase",
        "plan",
        "--action",
        "接受或修改 rerun",
    ]

    status1, out1 = main([*base]), capsys.readouterr().out
    assert status1 == 0
    assert json.loads(out1)["data"]["sent"] is True

    status2, out2 = main([*base]), capsys.readouterr().out
    assert status2 == 0
    assert json.loads(out2)["data"]["sent"] is False
    assert json.loads(out2)["data"]["dedup"] == "repeat"

    assert transport.sent == 1
