import json

from ai_workflow.cli import main


def test_cli_errors_use_stable_json_envelope(capsys) -> None:
    status = main(["config", "show", "--repo", "/missing"])
    payload = json.loads(capsys.readouterr().out)

    assert status != 0
    assert payload["ok"] is False
    assert payload["error"]["code"] == "config_not_found"
