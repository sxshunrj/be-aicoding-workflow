import json
from pathlib import Path

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


def _repo_config(repo: Path) -> None:
    (repo / ".ai-workflow.yaml").write_text(
        """
repository: demo
protected_paths: [.git/**, .ai-workflow/**]
adapter:
  source_paths: [src/**]
  test_paths: [tests/**]
  generated_test_destinations: [tests/generated]
  report_paths: [reports/integration.json]
""".strip(),
        encoding="utf-8",
    )


def test_cli_authorize_path_returns_stable_success_envelope(tmp_path: Path, capsys) -> None:
    _repo_config(tmp_path)

    status = main(
        [
            "config",
            "authorize-path",
            "--repo",
            str(tmp_path),
            "--kind",
            "input",
            "--path",
            "src/app.py",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert status == 0
    assert payload == {
        "ok": True,
        "data": {
            "authorized": True,
            "kind": "input",
            "path": "src/app.py",
        },
    }


def test_cli_authorize_path_fails_closed_for_protected_paths(
    tmp_path: Path, capsys
) -> None:
    _repo_config(tmp_path)

    status = main(
        [
            "config",
            "authorize-path",
            "--repo",
            str(tmp_path),
            "--kind",
            "input",
            "--path",
            ".git/config",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert status != 0
    assert payload["ok"] is False
    assert payload["error"]["code"] == "path_not_authorized"
