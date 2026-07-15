import hashlib
import json
from datetime import datetime
from pathlib import Path
import threading

import pytest

from ai_workflow.contracts.artifacts import ArtifactRef, ChildResult
from ai_workflow.errors import AppError
from ai_workflow.workflow.models import Phase
from ai_workflow.workflow.service import WorkflowService


def _service(tmp_path: Path, *, clock=lambda: datetime(2026, 7, 15, 12, 0, 0)):
    (tmp_path / ".ai-workflow.yaml").write_text(
        "repository: demo\n", encoding="utf-8"
    )
    contracts = tmp_path / "skill" / "references" / "agents"
    contracts.mkdir(parents=True)
    for name in ("common-phase-contract.md", "spec-writer.md"):
        (contracts / name).write_text(f"# {name}\n", encoding="utf-8")
    service = WorkflowService(tmp_path, clock=clock, id_factory=lambda: "abcdef")
    run = service.init(tmp_path, "abc123", "Write a technical specification")
    attempt = service.begin(run.run_id, Phase.SPEC, contracts.parents[1])
    return service, run, attempt


def _result(
    repo: Path,
    run_id: str,
    attempt_id: str,
    *,
    summary: str = "completed",
) -> Path:
    artifact = repo / "artifacts" / "spec-spec.md"
    artifact.parent.mkdir(exist_ok=True)
    artifact.write_text("# Spec\n", encoding="utf-8")
    result = ChildResult(
        run_id=run_id,
        phase=Phase.SPEC,
        child="spec",
        attempt_id=attempt_id,
        execution_mode="fresh",
        status="completed",
        summary=summary,
        artifact=ArtifactRef(
            path="artifacts/spec-spec.md",
            sha256=hashlib.sha256(artifact.read_bytes()).hexdigest(),
            schema_version=2,
            phase=Phase.SPEC,
            child="spec",
            source_revision="abc123",
        ),
        findings=(),
    )
    path = repo / "result.json"
    result.write(path)
    return path


def _events(service: WorkflowService, run_id: str) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in service._store(run_id).events_path.read_text().splitlines()
    ]


def test_stage_is_idempotent_for_identical_bytes_and_rejects_conflict(
    tmp_path: Path,
) -> None:
    service, run, attempt = _service(tmp_path)
    result = _result(tmp_path, run.run_id, attempt.attempt_id)

    first = service.stage(run.run_id, attempt.attempt_id, "spec", result)
    first_version = service.status(run.run_id).version
    second = service.stage(run.run_id, attempt.attempt_id, "spec", result)
    _result(
        tmp_path,
        run.run_id,
        attempt.attempt_id,
        summary="different serialized result",
    )

    assert second == first
    assert service.status(run.run_id).version == first_version
    assert sum(event["type"] == "child_result_staged" for event in _events(service, run.run_id)) == 1
    with pytest.raises(AppError, match="different staged result"):
        service.stage(run.run_id, attempt.attempt_id, "spec", result)


def test_stage_rejects_changed_artifact(tmp_path: Path) -> None:
    service, run, attempt = _service(tmp_path)
    result = _result(tmp_path, run.run_id, attempt.attempt_id)
    (tmp_path / "artifacts" / "spec-spec.md").write_text(
        "changed after result", encoding="utf-8"
    )

    with pytest.raises(AppError, match="artifact digest does not match"):
        service.stage(run.run_id, attempt.attempt_id, "spec", result)


def test_stage_parses_exactly_the_bytes_used_for_digest(tmp_path: Path) -> None:
    service, run, attempt = _service(tmp_path)
    result = _result(tmp_path, run.run_id, attempt.attempt_id)

    class OneReadPath(type(Path())):
        reads = 0

        def read_bytes(self):
            self.reads += 1
            if self.reads > 1:
                raise AssertionError("result path was read more than once")
            return super().read_bytes()

        def read_text(self, *args, **kwargs):
            raise AssertionError("result path was reopened as text")

    staged = service.stage(
        run.run_id, attempt.attempt_id, "spec", OneReadPath(result)
    )

    assert staged.result_digest == hashlib.sha256(result.read_bytes()).hexdigest()


def test_retry_repairs_missing_stage_event_once(tmp_path: Path, monkeypatch) -> None:
    service, run, attempt = _service(tmp_path)
    result = _result(tmp_path, run.run_id, attempt.attempt_id)
    events_path = service._store(run.run_id).events_path
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
        service.stage(run.run_id, attempt.attempt_id, "spec", result)

    repaired = service.stage(run.run_id, attempt.attempt_id, "spec", result)
    repaired_version = service.status(run.run_id).version
    again = service.stage(run.run_id, attempt.attempt_id, "spec", result)
    matching = [
        event
        for event in _events(service, run.run_id)
        if event["type"] == "child_result_staged"
        and event["data"]["attempt_id"] == attempt.attempt_id
    ]

    assert repaired == again
    assert service.status(run.run_id).version == repaired_version
    assert len(matching) == 1
    assert matching[0]["data"]["result_digest"] == repaired.result_digest


def test_fresh_begin_repairs_missing_stage_event_once(
    tmp_path: Path, monkeypatch
) -> None:
    service, run, attempt = _service(tmp_path)
    result = _result(tmp_path, run.run_id, attempt.attempt_id)
    events_path = service._store(run.run_id).events_path
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
        service.stage(run.run_id, attempt.attempt_id, "spec", result)

    recovered = WorkflowService(tmp_path)
    resumed = recovered.begin(run.run_id, Phase.SPEC, tmp_path / "skill")
    repaired_version = recovered.status(run.run_id).version
    stable = recovered.begin(run.run_id, Phase.SPEC, tmp_path / "skill")
    matching = [
        event
        for event in _events(recovered, run.run_id)
        if event["type"] == "child_result_staged"
        and event["data"]["attempt_id"] == attempt.attempt_id
        and event["data"]["child"] == "spec"
    ]

    assert resumed == stable
    assert resumed.dispatch_plan[0].action == "already_staged"
    assert recovered.status(run.run_id).version == repaired_version
    assert len(matching) == 1


def test_competing_stage_reconciliation_is_serialized_without_duplicate(
    tmp_path: Path,
) -> None:
    service, run, attempt = _service(tmp_path)
    result = _result(tmp_path, run.run_id, attempt.attempt_id)
    services = (WorkflowService(tmp_path), WorkflowService(tmp_path))
    barrier = threading.Barrier(2)
    staged = []
    failures = []

    def stage(candidate: WorkflowService) -> None:
        try:
            barrier.wait()
            staged.append(
                candidate.stage(run.run_id, attempt.attempt_id, "spec", result)
            )
        except BaseException as error:  # surfaced below with full repr
            failures.append(error)

    threads = [threading.Thread(target=stage, args=(candidate,)) for candidate in services]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(2)

    assert failures == []
    assert len(staged) == 2 and staged[0] == staged[1]
    assert sum(event["type"] == "child_result_staged" for event in _events(service, run.run_id)) == 1


def test_reconciliation_truncates_only_incomplete_jsonl_tail(
    tmp_path: Path, monkeypatch
) -> None:
    service, run, attempt = _service(tmp_path)
    result = _result(tmp_path, run.run_id, attempt.attempt_id)
    events_path = service._store(run.run_id).events_path
    real_open = Path.open
    failed = False

    def partial_append(path, mode="r", *args, **kwargs):
        nonlocal failed
        stream = real_open(path, mode, *args, **kwargs)
        if path == events_path and mode == "a" and not failed:
            failed = True
            stream.write('{"type":"child_result_staged"')
            stream.flush()
            stream.close()
            raise OSError("partial append")
        return stream

    monkeypatch.setattr(Path, "open", partial_append)
    with pytest.raises(OSError, match="partial append"):
        service.stage(run.run_id, attempt.attempt_id, "spec", result)

    service.stage(run.run_id, attempt.attempt_id, "spec", result)

    assert events_path.read_bytes().endswith(b"\n")
    assert sum(event["type"] == "child_result_staged" for event in _events(service, run.run_id)) == 1


def test_reconciliation_never_discards_malformed_complete_line(
    tmp_path: Path, monkeypatch
) -> None:
    service, run, attempt = _service(tmp_path)
    result = _result(tmp_path, run.run_id, attempt.attempt_id)
    events_path = service._store(run.run_id).events_path
    real_open = Path.open
    failed = False

    def fail_once(path, mode="r", *args, **kwargs):
        nonlocal failed
        if path == events_path and mode == "a" and not failed:
            failed = True
            raise OSError("append failed")
        return real_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_once)
    with pytest.raises(OSError):
        service.stage(run.run_id, attempt.attempt_id, "spec", result)
    with real_open(events_path, "a", encoding="utf-8") as stream:
        stream.write('{"broken":\n')
    before = events_path.read_bytes()

    with pytest.raises(AppError) as error:
        service.stage(run.run_id, attempt.attempt_id, "spec", result)

    assert error.value.code == "invalid_state"
    assert events_path.read_bytes() == before


def test_stage_rejects_tampered_staged_bytes(tmp_path: Path) -> None:
    service, run, attempt = _service(tmp_path)
    result = _result(tmp_path, run.run_id, attempt.attempt_id)
    service.stage(run.run_id, attempt.attempt_id, "spec", result)
    staged_path = service._store(run.run_id).staged_path(attempt.attempt_id, "spec")
    staged_path.write_text("{}", encoding="utf-8")

    with pytest.raises(AppError, match="staged result evidence"):
        service.stage(run.run_id, attempt.attempt_id, "spec", result)
