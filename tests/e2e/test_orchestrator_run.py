"""End-to-end coverage for the code-owned orchestrator loop.

These tests drive the loop with the deterministic fake child (no LLM, no
network) and prove the two properties that matter:

* a full four-phase run reaches ``completed`` with no hand-written CLI calls;
* a child cannot talk its way past a command the harness observed failing.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

from ai_workflow.harness.evidence import EvidenceRecorder
from ai_workflow.harness.gates import BlockedView, GateDecision, GateOutcome, ReviewView
from ai_workflow.harness.loop import RunLoop
from ai_workflow.harness.runner import ChildOutcome, ChildRequest
from ai_workflow.workflow.service import WorkflowService
from tests.e2e.fake_agent import CliDriver, FakeAgent


class FakeChildRunner:
    """Deterministic child runner backed by the existing fake agent."""

    def __init__(self, repo: Path) -> None:
        self.agent = FakeAgent(repo)

    def run(self, request: ChildRequest, result_path: Path) -> ChildOutcome:
        assert request.packet_file is not None, f"{request.node} has no dispatch packet"
        produced = self.agent.run(Path(request.packet_file))
        return ChildOutcome(request.node, request.child, produced.read_bytes())


class AcceptingGate:
    """Accepts every review gate and records what it was asked."""

    def __init__(self) -> None:
        self.reviews: list[ReviewView] = []

    def review(self, view: ReviewView) -> GateOutcome:
        self.reviews.append(view)
        return GateOutcome(GateDecision.ACCEPT)

    def blocked(self, view: BlockedView) -> GateOutcome:
        return GateOutcome(GateDecision.BLOCK, reason="unexpected block")


class BlockOnFailingEvidenceGate:
    """Stops for a human when the harness itself observed a failing command."""

    def review(self, view: ReviewView) -> GateOutcome:
        if view.phase == "verify" and view.proposed_reruns:
            return GateOutcome(
                GateDecision.BLOCK,
                reason="harness evidence shows a failing verify command",
            )
        return GateOutcome(GateDecision.ACCEPT)

    def blocked(self, view: BlockedView) -> GateOutcome:
        return GateOutcome(GateDecision.BLOCK, reason=view.reason)


def _service(repo: Path) -> WorkflowService:
    return WorkflowService(repo, id_factory=lambda: "abcdef")


def test_loop_drives_a_full_run_to_completion(project_template, tmp_path: Path) -> None:
    repo = project_template.copy_to(tmp_path / "language-neutral")
    driver = CliDriver(repo)
    run_id = driver.workflow_init()["run_id"]

    gate = AcceptingGate()
    loop = RunLoop(
        _service(repo),
        FakeChildRunner(repo),
        gate,
        skill_dir=repo / ".test-skill",
        evidence=EvidenceRecorder(),
    )

    outcome = loop.run(run_id)

    assert outcome.status == "completed"
    assert outcome.stopped_reason == ""
    assert driver.workflow_status(run_id)["status"] == "completed"
    assert {view.phase for view in gate.reviews} == {"spec", "plan", "implement", "verify"}
    kinds = [event.kind for event in outcome.events]
    assert kinds.count("transition") == 4
    # full profile minus the disabled integration_test node
    assert kinds.count("stage") == 7
    assert kinds[-1] == "terminal"

    summary = _service(repo).summary(run_id)
    observed = {record["child"]: record for record in summary.harness_evidence}
    assert set(observed) == {"build", "unit_test"}
    assert all(record["exit_status"] == 0 for record in observed.values())
    assert observed["build"]["node"] == "verify.build"


def test_failing_harness_evidence_blocks_the_verify_phase(project_template, tmp_path: Path) -> None:
    repo = project_template.copy_to(tmp_path / "language-neutral")
    config = repo / ".ai-workflow.yaml"
    config.write_text(
        config.read_text(encoding="utf-8").replace("verify.sh, unit-test", "verify.sh, bogus"),
        encoding="utf-8",
    )
    subprocess.run(
        ["git", "commit", "-am", "point unit_test at a failing command"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    driver = CliDriver(repo)
    run_id = driver.workflow_init()["run_id"]
    harness_root = _service(repo).harness_directory(run_id)

    loop = RunLoop(
        _service(repo),
        FakeChildRunner(repo),
        BlockOnFailingEvidenceGate(),
        skill_dir=repo / ".test-skill",
        evidence=EvidenceRecorder(),
    )

    outcome = loop.run(run_id)

    assert outcome.status == "blocked"
    assert driver.workflow_status(run_id)["status"] == "blocked"

    review = next(
        event
        for event in outcome.events
        if event.kind == "review" and event.data.get("phase") == "verify"
    )
    reruns = review.data["reruns"]
    assert isinstance(reruns, dict)
    assert "verify.unit_test" in reruns
    assert "exit 2" in str(reruns["verify.unit_test"])

    evidence_files = sorted(harness_root.rglob("*unit_test.json"))
    assert evidence_files, "the harness must record what it observed"
    payload = json.loads(evidence_files[0].read_text(encoding="utf-8"))
    assert payload["exit_status"] != 0
    assert payload["child"] == "unit_test"
