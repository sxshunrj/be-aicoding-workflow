import json
from pathlib import Path

from ai_workflow.cli import main


def _config(repo: Path) -> None:
    (repo / ".ai-workflow.yaml").write_text("repository: demo\n", encoding="utf-8")


def _call(capsys, argv: list[str]) -> tuple[int, dict[str, object]]:
    status = main(argv)
    return status, json.loads(capsys.readouterr().out)


def test_workflow_lifecycle_commands(tmp_path: Path, capsys) -> None:
    _config(tmp_path)
    status, init = _call(
        capsys,
        ["workflow", "init", "--repo", str(tmp_path), "--source-revision", "abc123"],
    )
    assert status == 0
    run_id = init["data"]["run_id"]
    assert run_id.startswith("RUN-")

    status, begin = _call(
        capsys,
        ["workflow", "begin", "--repo", str(tmp_path), "--run-id", run_id, "--phase", "spec"],
    )
    assert status == 0
    assert begin["data"]["phase"] == "spec"

    status, blocked = _call(
        capsys,
        ["workflow", "block", "--repo", str(tmp_path), "--run-id", run_id, "--reason", "waiting"],
    )
    assert status == 0
    assert blocked["data"]["status"] == "blocked"

    status, resumed = _call(
        capsys,
        ["workflow", "resume", "--repo", str(tmp_path), "--run-id", run_id],
    )
    assert status == 0
    assert resumed["data"]["status"] == "running"

    status, aborted = _call(
        capsys,
        ["workflow", "abort", "--repo", str(tmp_path), "--run-id", run_id],
    )
    assert status == 0
    assert aborted["data"]["status"] == "aborted"

    status, shown = _call(
        capsys,
        ["workflow", "status", "--repo", str(tmp_path), "--run-id", run_id],
    )
    assert status == 0
    assert shown["data"]["version"] == 4


def test_transition_requires_valid_current_node(tmp_path: Path, capsys) -> None:
    _config(tmp_path)
    _, init = _call(
        capsys,
        ["workflow", "init", "--repo", str(tmp_path), "--source-revision", "abc123"],
    )
    status, result = _call(
        capsys,
        ["workflow", "transition", "--repo", str(tmp_path), "--run-id", init["data"]["run_id"], "--accept"],
    )
    assert status != 0
    assert result["error"]["code"] == "invalid_transition"
