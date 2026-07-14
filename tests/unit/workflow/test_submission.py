import hashlib

import pytest

from ai_workflow.contracts.artifacts import ArtifactRef, ChildResult
from ai_workflow.errors import AppError
from ai_workflow.workflow.models import Phase
from ai_workflow.workflow.service import WorkflowService


def _service(tmp_path):
    (tmp_path / ".ai-workflow.yaml").write_text("repository: demo\n", encoding="utf-8")
    service = WorkflowService(tmp_path, id_factory=lambda: "abcdef")
    return service, service.init(tmp_path, "abc123")


def _result(tmp_path, attempt, artifact):
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    result = ChildResult("completed", "done", ArtifactRef(str(artifact), digest, 1, Phase.SPEC, "abc123"), ())
    path = tmp_path / "result.json"
    result.write(path)
    return path


def test_submit_accepts_matching_artifact_digest_idempotently(tmp_path) -> None:
    service, run = _service(tmp_path)
    attempt = service.begin(run.run_id, Phase.SPEC)
    artifact = tmp_path / "technical-spec.md"
    artifact.write_text("# Spec", encoding="utf-8")
    result = _result(tmp_path, attempt, artifact)

    first = service.submit(run.run_id, attempt.attempt_id, result)
    second = service.submit(run.run_id, attempt.attempt_id, result)

    assert first.nodes["spec"].status == "valid"
    assert second.version == first.version


def test_submit_rejects_changed_artifact(tmp_path) -> None:
    service, run = _service(tmp_path)
    attempt = service.begin(run.run_id, Phase.SPEC)
    artifact = tmp_path / "technical-spec.md"
    artifact.write_text("original", encoding="utf-8")
    result = _result(tmp_path, attempt, artifact)
    artifact.write_text("changed after result", encoding="utf-8")

    with pytest.raises(AppError, match="artifact digest does not match"):
        service.submit(run.run_id, attempt.attempt_id, result)


def test_submit_rejects_artifact_that_escapes_repository(tmp_path) -> None:
    service, run = _service(tmp_path)
    attempt = service.begin(run.run_id, Phase.SPEC)
    artifact = tmp_path.parent / "outside-artifact.md"
    artifact.write_text("outside", encoding="utf-8")
    result = _result(tmp_path, attempt, artifact)

    with pytest.raises(AppError, match="artifact path escapes repository"):
        service.submit(run.run_id, attempt.attempt_id, result)
