"""Detached runs: start a loop in the background and poll it to a decision point."""

from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import sys
import time

from ai_workflow.cli import main


def _cli(argv: list[str]) -> dict[str, object]:
    buffer = StringIO()
    with redirect_stdout(buffer):
        status = main(argv)
    payload = json.loads(buffer.getvalue())
    assert payload["ok"] is True, payload
    assert status == 0, payload
    data = payload["data"]
    assert isinstance(data, dict)
    return data


def _cli_error(argv: list[str]) -> dict[str, object]:
    buffer = StringIO()
    with redirect_stdout(buffer):
        status = main(argv)
    payload = json.loads(buffer.getvalue())
    assert payload["ok"] is False, payload
    assert status != 0, payload
    error = payload["error"]
    assert isinstance(error, dict)
    return error


def _child_template() -> str:
    return (
        f"{sys.executable} {Path(__file__).with_name('fake_agent.py')} "
        "--prompt-file {prompt_file} --result {result_file}"
    )


def test_detached_run_reports_progress_and_a_final_result(project_template, tmp_path: Path) -> None:
    repo = project_template.copy_to(tmp_path / "language-neutral")
    from tests.e2e.fake_agent import CliDriver

    run_id = CliDriver(repo).workflow_init()["run_id"]

    handle = _cli([
        "run",
        "--repo", str(repo),
        "--run-id", str(run_id),
        "--skill-dir", str(repo / ".test-skill"),
        "--child-command", _child_template(),
        "--gate", "refuse",
        "--detach",
    ])

    assert handle["status"] == "started"
    assert isinstance(handle["pid"], int) and handle["pid"] > 0
    progress = Path(str(handle["progress_path"]))
    result_path = Path(str(handle["result_path"]))

    events: list[dict[str, object]] = []
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if progress.is_file():
            events = [
                json.loads(line)
                for line in progress.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            if any(event["kind"] == "run_finished" for event in events):
                break
        time.sleep(0.05)

    kinds = [event["kind"] for event in events]
    assert "run_finished" in kinds, kinds
    assert "begin" in kinds
    assert "review" in kinds
    finished = next(event for event in events if event["kind"] == "run_finished")
    assert finished["data"]["status"] == "blocked"  # the refusing gate parks the run
    assert "timestamp" not in finished  # progress lines carry `time`, not the event schema

    payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert payload["ok"] is True
    assert payload["data"]["status"] == "blocked"
    assert payload["data"]["events"][-1]["kind"] == "blocked_waiting_for_human"

    status = _cli(["run-status", "--repo", str(repo), "--run-id", str(run_id)])
    assert status["status"] == "blocked"
    assert status["current_phase"] == "spec"
    assert status["running"] is False
    assert status["progress_path"] == str(progress)
    assert status["result_path"] == str(result_path)
    progress_kinds = [event["kind"] for event in status["progress"]]
    assert "run_finished" in progress_kinds
    assert isinstance(status["result"], dict)
    assert status["result"]["data"]["status"] == "blocked"


def test_detach_refuses_an_interactive_gate(tmp_path: Path) -> None:
    error = _cli_error([
        "run",
        "--repo", str(tmp_path),
        "--run-id", "RUN-20260101-000000-abcdef",
        "--child-command", "true",
        "--gate", "prompt",
        "--detach",
    ])

    assert error["code"] == "invalid_arguments"
    assert "no stdin" in str(error["message"])


def test_result_file_requires_detach(tmp_path: Path) -> None:
    error = _cli_error([
        "run",
        "--repo", str(tmp_path),
        "--run-id", "RUN-20260101-000000-abcdef",
        "--child-command", "true",
        "--result-file", str(tmp_path / "result.json"),
    ])

    assert error["code"] == "invalid_arguments"
    assert "--detach" in str(error["message"])
