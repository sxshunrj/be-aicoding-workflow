import hashlib

from ai_workflow.contracts.artifacts import ArtifactRef, ChildResult
from ai_workflow.workflow.models import Phase
from ai_workflow.workflow.service import WorkflowService


def test_service_recovers_submitted_phase_from_disk(tmp_path) -> None:
    (tmp_path / ".ai-workflow.yaml").write_text("repository: demo\n", encoding="utf-8")
    service = WorkflowService(tmp_path, id_factory=lambda: "abcdef")
    run = service.init(tmp_path, "abc123")
    attempt = service.begin(run.run_id, Phase.SPEC)
    artifact = tmp_path / "spec.md"
    artifact.write_text("spec", encoding="utf-8")
    result = ChildResult("completed", "done", ArtifactRef(str(artifact), hashlib.sha256(b"spec").hexdigest(), 1, Phase.SPEC, "abc123"), ())
    result_path = tmp_path / "result.json"
    result.write(result_path)
    service.submit(run.run_id, attempt.attempt_id, result_path)

    recovered = WorkflowService(tmp_path)
    assert recovered.status(run.run_id).current_phase == "plan"
    assert recovered.begin(run.run_id, Phase.PLAN).number == 1
