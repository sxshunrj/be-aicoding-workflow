"""Unit coverage for the orchestrator pieces that need no run state."""

from __future__ import annotations

import io
import json
from pathlib import Path

from ai_workflow.errors import AppError
from ai_workflow.harness.evidence import EvidenceRecord, EvidenceRecorder
from ai_workflow.harness.gates import (
    BlockedView,
    GateDecision,
    PromptHumanGate,
    RefusingGate,
    ReviewView,
    parse_rerun_line,
)
from ai_workflow.harness.loop import DeterministicProposer
from ai_workflow.harness.runner import ChildRequest, SubprocessChildRunner
from ai_workflow.workflow.models import Phase
from ai_workflow.workflow.service import DispatchItem, PhaseAggregate, PhaseAttempt


def _attempt(*items: DispatchItem, phase: Phase = Phase.VERIFY) -> PhaseAttempt:
    return PhaseAttempt("RUN-20260101-000000-abcdef", phase.value, 1, "verify-1-abcdef", tuple(items))


def _item(node: str, child: str, action: str = "dispatch") -> DispatchItem:
    return DispatchItem(node, child, "child_backed", action, None, None, None)


def _aggregate(children: tuple[dict[str, object], ...]) -> PhaseAggregate:
    return PhaseAggregate("RUN-20260101-000000-abcdef", "verify", "verify-1-abcdef", "completed", children)


def _evidence(node: str, child: str, *, exit_status: int) -> EvidenceRecord:
    return EvidenceRecord(
        node=node,
        child=child,
        argv=("bash", "verify.sh"),
        cwd="/repo",
        exit_status=exit_status,
        duration_ms=1,
        output_digest="0" * 64,
        output_excerpt="",
        output_truncated=False,
        path=f"/harness/evidence/{child}.json",
    )


def test_parse_rerun_line_accepts_and_rejects() -> None:
    assert parse_rerun_line("verify.unit_test=flaky in suite A") == (
        "verify.unit_test",
        "flaky in suite A",
    )
    for invalid in ("no-separator", "=reason", "node="):
        try:
            parse_rerun_line(invalid)
        except AppError as error:
            assert error.code == "invalid_arguments"
        else:  # pragma: no cover - the assertion below is the failure mode
            raise AssertionError(f"{invalid!r} should not parse")


def test_refusing_gate_never_invents_a_human_decision() -> None:
    gate = RefusingGate()
    review = gate.review(
        ReviewView("RUN-1", "verify", "a" * 64, "human_review", (), "summary")
    )
    assert review.decision is GateDecision.BLOCK
    assert "human decision" in review.reason
    blocked = gate.blocked(BlockedView("RUN-1", "verify", "tests fail"))
    assert blocked.decision is GateDecision.BLOCK
    assert "tests fail" in blocked.reason


def test_prompt_gate_keeps_stdout_clean(capsys, monkeypatch) -> None:
    """The CLI reserves stdout for one JSON envelope; gate I/O must use stderr."""
    monkeypatch.setattr("sys.stdin", io.StringIO("1\n"))
    gate = PromptHumanGate()
    outcome = gate.review(ReviewView("RUN-1", "spec", "b" * 64, "human_review", (), "summary"))
    captured = capsys.readouterr()
    assert outcome.decision is GateDecision.ACCEPT
    assert captured.out == ""
    assert "review gate" in captured.err


def test_prompt_gate_reads_a_rerun_proposal(capsys, monkeypatch) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("2\nverify.unit_test=flaky\n\n"))
    gate = PromptHumanGate()
    outcome = gate.review(ReviewView("RUN-1", "verify", "c" * 64, "human_review", (), "summary"))
    assert outcome.decision is GateDecision.RERUN
    assert outcome.rerun_map() == {"verify.unit_test": "flaky"}
    assert capsys.readouterr().out == ""


def test_proposer_reruns_unable_children_and_failing_evidence() -> None:
    attempt = _attempt(_item("verify.unit_test", "unit_test"), _item("verify.build", "build"))
    aggregate = _aggregate(
        (
            {"node": "verify.unit_test", "child": "unit_test", "status": "unable_to_complete"},
            {"node": "verify.build", "child": "build", "status": "completed"},
        )
    )
    failing = _evidence("verify.build", "build", exit_status=2)

    proposal = DeterministicProposer().propose(
        phase=Phase.VERIFY, attempt=attempt, aggregate=aggregate, evidence=(failing,)
    )

    assert set(proposal) == {"verify.unit_test", "verify.build"}
    assert "unable_to_complete" in proposal["verify.unit_test"]
    assert "exit 2" in proposal["verify.build"]


def test_proposer_stays_silent_when_children_and_evidence_are_clean() -> None:
    attempt = _attempt(_item("verify.build", "build"))
    aggregate = _aggregate(({"node": "verify.build", "child": "build", "status": "completed"},))
    proposal = DeterministicProposer().propose(
        phase=Phase.VERIFY,
        attempt=attempt,
        aggregate=aggregate,
        evidence=(_evidence("verify.build", "build", exit_status=0),),
    )
    assert proposal == {}


def test_subprocess_runner_reads_result_file(tmp_path: Path) -> None:
    template = (
        "python3",
        "-c",
        "import pathlib,sys,json;pathlib.Path(sys.argv[1]).write_text(json.dumps({'schema_version':2,'child':'build'}))",
        "{result_file}",
    )
    runner = SubprocessChildRunner(template, repo_root=tmp_path)
    request = ChildRequest("verify.build", "build", "dispatch", None, None)
    outcome = runner.run(request, tmp_path / "results" / "build.json")
    assert outcome.ok
    assert json.loads(outcome.result_bytes.decode())["child"] == "build"


def test_subprocess_runner_reads_stdout(tmp_path: Path) -> None:
    template = ("python3", "-c", "print('noise');print('{\"schema_version\": 2, \"child\": \"unit_test\"}')")
    runner = SubprocessChildRunner(template, repo_root=tmp_path)
    request = ChildRequest("verify.unit_test", "unit_test", "dispatch", None, None)
    outcome = runner.run(request, tmp_path / "never-written.json")
    assert outcome.ok
    assert json.loads(outcome.result_bytes.decode())["child"] == "unit_test"


def test_subprocess_runner_reports_missing_result_as_transport_failure(tmp_path: Path) -> None:
    runner = SubprocessChildRunner(("python3", "-c", "print('nothing useful')"), repo_root=tmp_path)
    request = ChildRequest("verify.build", "build", "dispatch", None, None)
    outcome = runner.run(request, tmp_path / "missing.json")
    assert not outcome.ok
    assert "no ChildResult" in (outcome.failure or "")


def test_subprocess_runner_reports_missing_executable(tmp_path: Path) -> None:
    runner = SubprocessChildRunner(("definitely-not-a-real-binary-xyz",), repo_root=tmp_path)
    request = ChildRequest("verify.build", "build", "dispatch", None, None)
    outcome = runner.run(request, tmp_path / "missing.json")
    assert not outcome.ok
    assert "could not start" in (outcome.failure or "")


def test_evidence_recorder_persists_what_it_observed(tmp_path: Path) -> None:
    recorder = EvidenceRecorder(tmp_path / "harness")
    record = recorder.record(
        run_id="RUN-20260101-000000-abcdef",
        attempt_id="verify-1-abcdef",
        node="verify.build",
        child="build",
        command=("python3", "-c", "print('built ok')"),
        cwd=tmp_path,
    )
    assert record.passed
    assert record.exit_status == 0
    payload = json.loads(Path(record.path).read_text(encoding="utf-8"))
    assert payload["node"] == "verify.build"
    assert payload["exit_status"] == 0
    assert payload["output_digest"] == record.output_digest


def test_evidence_recorder_captures_non_zero_exit(tmp_path: Path) -> None:
    recorder = EvidenceRecorder(tmp_path / "harness")
    record = recorder.record(
        run_id="RUN-20260101-000000-abcdef",
        attempt_id="verify-1-abcdef",
        node="verify.unit_test",
        child="unit_test",
        command=("python3", "-c", "import sys;print('boom');sys.exit(2)"),
        cwd=tmp_path,
    )
    assert not record.passed
    assert record.exit_status == 2
    assert "boom" in record.output_excerpt
