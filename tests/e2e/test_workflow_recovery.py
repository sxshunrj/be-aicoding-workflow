import hashlib
from pathlib import Path

from ai_workflow.contracts.artifacts import ArtifactRef, ChildResult
from ai_workflow.workflow.graph import NodeValidity
from ai_workflow.workflow.models import Phase
from ai_workflow.workflow.service import WorkflowService


def test_service_recovers_staged_and_finalized_phase_from_disk(tmp_path: Path) -> None:
    (tmp_path / ".ai-workflow.yaml").write_text(
        "repository: demo\n", encoding="utf-8"
    )
    contracts = tmp_path / "skill" / "references" / "agents"
    contracts.mkdir(parents=True)
    for name in ("common-phase-contract.md", "spec-writer.md"):
        (contracts / name).write_text(f"# {name}\n", encoding="utf-8")
    service = WorkflowService(tmp_path, id_factory=lambda: "abcdef")
    run = service.init(tmp_path, "abc123", "Recover workflow state")
    attempt = service.begin(run.run_id, Phase.SPEC, contracts.parents[1])
    artifact = tmp_path / "artifacts" / "spec-spec.md"
    artifact.parent.mkdir()
    artifact.write_text("spec", encoding="utf-8")
    result = ChildResult(
        run.run_id,
        Phase.SPEC,
        "spec",
        attempt.attempt_id,
        "fresh",
        "completed",
        "done",
        ArtifactRef(
            "artifacts/spec-spec.md",
            hashlib.sha256(b"spec").hexdigest(),
            2,
            Phase.SPEC,
            "spec",
            "abc123",
        ),
        (),
    )
    result_path = tmp_path / "result.json"
    result.write(result_path)
    service.stage(run.run_id, attempt.attempt_id, "spec", result_path)
    expected = service.finalize(run.run_id, attempt.attempt_id)

    recovered = WorkflowService(tmp_path)

    assert recovered.status(run.run_id).current_phase == "spec"
    assert (
        recovered.status(run.run_id).run_graph["spec.spec"].validity
        is NodeValidity.VALID
    )
    assert recovered.finalize(run.run_id, attempt.attempt_id) == expected

    decision = recovered.review(run.run_id, {})
    assert WorkflowService(tmp_path).review(run.run_id, {}) == decision
    WorkflowService(tmp_path).record_review_acceptance(run.run_id, decision.digest)

    transitioned = WorkflowService(tmp_path).transition(run.run_id)
    assert transitioned.current_phase == "plan"
    assert "review_gate" not in transitioned.artifacts
