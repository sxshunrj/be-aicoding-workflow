import json

import pytest

from ai_workflow.cli import main


def test_cli_errors_use_stable_json_envelope(capsys) -> None:
    status = main(["config", "show", "--repo", "/missing"])
    payload = json.loads(capsys.readouterr().out)

    assert status != 0
    assert payload["ok"] is False
    assert payload["error"]["code"] == "config_not_found"


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["unknown"],
        ["config", "show", "--repo"],
    ],
)
def test_cli_parser_errors_use_stable_json_envelope(argv, capsys) -> None:
    status = main(argv)
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert status != 0
    assert captured.err == ""
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_arguments"
    assert payload["error"]["details"] == {}
