import hashlib
import json
from pathlib import Path

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


def test_retry_repairs_missing_submission_event_once(tmp_path, monkeypatch) -> None:
    service, run = _service(tmp_path)
    attempt = service.begin(run.run_id, Phase.SPEC)
    artifact = tmp_path / "technical-spec.md"
    artifact.write_text("# Spec", encoding="utf-8")
    result = _result(tmp_path, attempt, artifact)
    events_path = tmp_path / ".ai-workflow" / "runs" / run.run_id / "events.jsonl"
    real_open = Path.open
    failed = False

    def fail_event_append(path, mode="r", *args, **kwargs):
        nonlocal failed
        if path == events_path and mode == "a" and not failed:
            failed = True
            raise OSError("injected event append failure")
        return real_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_event_append)
    with pytest.raises(OSError, match="injected"):
        service.submit(run.run_id, attempt.attempt_id, result)

    repaired = service.submit(run.run_id, attempt.attempt_id, result)
    again = service.submit(run.run_id, attempt.attempt_id, result)
    events = [json.loads(line) for line in events_path.read_text().splitlines()]
    matching = [event for event in events if event["type"] == "result_submitted"
                and event["data"]["attempt_id"] == attempt.attempt_id]

    assert repaired.version == again.version == 2
    assert len(matching) == 1
    assert matching[0]["version"] == repaired.version
    assert matching[0]["data"]["run_id"] == run.run_id
    assert matching[0]["data"]["node"] == "spec"
    assert matching[0]["data"]["artifact_digest"] == hashlib.sha256(b"# Spec").hexdigest()


def test_submit_parses_the_same_result_bytes_used_for_digest(tmp_path) -> None:
    service, run = _service(tmp_path)
    attempt = service.begin(run.run_id, Phase.SPEC)
    artifact = tmp_path / "technical-spec.md"
    artifact.write_text("# Spec", encoding="utf-8")
    result = _result(tmp_path, attempt, artifact)

    class OneReadPath(type(Path())):
        reads = 0

        def read_bytes(self):
            self.reads += 1
            if self.reads > 1:
                raise AssertionError("result path was read more than once")
            return super().read_bytes()

        def read_text(self, *args, **kwargs):
            raise AssertionError("result path was reopened as text")

    state = service.submit(run.run_id, attempt.attempt_id, OneReadPath(result))

    assert state.nodes["spec"].status == "valid"
