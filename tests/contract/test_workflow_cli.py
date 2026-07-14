import json
from pathlib import Path

import pytest

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


def test_transition_accepts_repeatable_reruns(tmp_path: Path, capsys) -> None:
    _config(tmp_path)
    _, init = _call(capsys, ["workflow", "init", "--repo", str(tmp_path), "--source-revision", "abc123"])
    run_id = init["data"]["run_id"]
    for phase in ("spec", "plan", "implement", "verify"):
        _call(capsys, ["workflow", "begin", "--repo", str(tmp_path), "--run-id", run_id, "--phase", phase])
        if phase != "verify":
            _call(capsys, ["workflow", "transition", "--repo", str(tmp_path), "--run-id", run_id, "--accept"])

    status, result = _call(capsys, ["workflow", "transition", "--repo", str(tmp_path), "--run-id", run_id, "--rerun", "implement=missing branch", "--rerun", "verify=check again"])

    assert status == 0
    assert result["data"]["current_phase"] == "implement"


@pytest.mark.parametrize("value", ["unknown=reason", "spec=", "malformed", "=reason"])
def test_rejects_malformed_rerun_values(tmp_path: Path, capsys, value: str) -> None:
    status, result = _call(capsys, ["workflow", "transition", "--repo", str(tmp_path), "--run-id", "RUN-20260714-123456-abcdef", "--rerun", value])

    assert status != 0
    assert result["error"]["code"] == "invalid_arguments"


def test_rejects_duplicate_rerun_phase(tmp_path: Path, capsys) -> None:
    status, result = _call(capsys, ["workflow", "transition", "--repo", str(tmp_path), "--run-id", "RUN-20260714-123456-abcdef", "--rerun", "spec=one", "--rerun", "spec=two"])

    assert status != 0
    assert result["error"]["code"] == "invalid_arguments"


@pytest.mark.parametrize("run_id", ["../escape", "/tmp/escape"])
def test_hostile_run_id_uses_json_error(tmp_path: Path, capsys, run_id: str) -> None:
    status, result = _call(capsys, ["workflow", "status", "--repo", str(tmp_path), "--run-id", run_id])

    assert status != 0
    assert result["error"]["code"] == "invalid_run_id"


def test_corrupt_state_uses_json_error(tmp_path: Path, capsys) -> None:
    run_id = "RUN-20260714-123456-abcdef"
    run_dir = tmp_path / ".ai-workflow" / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "state.yaml").write_text("nodes: [broken\n", encoding="utf-8")

    status, result = _call(capsys, ["workflow", "status", "--repo", str(tmp_path), "--run-id", run_id])

    assert status != 0
    assert result["error"]["code"] == "invalid_state"
