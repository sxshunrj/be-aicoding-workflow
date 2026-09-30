"""Run-state coverage for harness evidence persisted through the helper."""

from __future__ import annotations

import pytest

from ai_workflow.errors import AppError
from ai_workflow.workflow.models import Phase
from ai_workflow.workflow.service import WorkflowService


def _run(tmp_path):
    (tmp_path / ".ai-workflow.yaml").write_text("repository: demo\n", encoding="utf-8")
    contracts = tmp_path / "skill" / "references" / "agents"
    contracts.mkdir(parents=True)
    for name in ("common-phase-contract.md", "spec-writer.md"):
        (contracts / name).write_text(f"# {name}\n", encoding="utf-8")
    service = WorkflowService(tmp_path, id_factory=lambda: "abcdef")
    run = service.init(tmp_path, "abc123", "Persist harness evidence")
    attempt = service.begin(run.run_id, Phase.SPEC, contracts.parents[1])
    return service, run.run_id, attempt


PAYLOAD: dict[str, object] = {
    "node": "spec.spec",
    "child": "spec",
    "argv": ["bash", "verify.sh", "build"],
    "cwd": "/repo",
    "exit_status": 0,
    "duration_ms": 12,
    "output_digest": "0" * 64,
    "output_excerpt": "built ok",
    "output_truncated": False,
}


def test_recorded_evidence_is_registered_and_summarised(tmp_path) -> None:
    service, run_id, attempt = _run(tmp_path)

    registration = service.record_evidence(
        run_id, attempt_id=attempt.attempt_id, node="spec.spec", child="spec", payload=PAYLOAD
    )

    assert registration["exit_status"] == 0
    stored = tmp_path / ".ai-workflow" / "runs" / run_id / str(registration["path"])
    assert stored.is_file()
    summary = service.summary(run_id)
    assert len(summary.harness_evidence) == 1
    assert summary.harness_evidence[0]["child"] == "spec"
    assert summary.to_dict()["harness_evidence"][0]["sha256"] == registration["sha256"]


def test_recording_the_same_observation_twice_is_idempotent(tmp_path) -> None:
    service, run_id, attempt = _run(tmp_path)

    first = service.record_evidence(
        run_id, attempt_id=attempt.attempt_id, node="spec.spec", child="spec", payload=PAYLOAD
    )
    second = service.record_evidence(
        run_id, attempt_id=attempt.attempt_id, node="spec.spec", child="spec", payload=PAYLOAD
    )

    assert first == second
    assert len(service.summary(run_id).harness_evidence) == 1


def test_recording_a_different_observation_for_the_same_child_conflicts(tmp_path) -> None:
    service, run_id, attempt = _run(tmp_path)
    service.record_evidence(
        run_id, attempt_id=attempt.attempt_id, node="spec.spec", child="spec", payload=PAYLOAD
    )

    with pytest.raises(AppError) as error:
        service.record_evidence(
            run_id,
            attempt_id=attempt.attempt_id,
            node="spec.spec",
            child="spec",
            payload={**PAYLOAD, "exit_status": 1},
        )

    assert error.value.code == "evidence_conflict"


def test_evidence_for_an_unknown_attempt_is_rejected(tmp_path) -> None:
    service, run_id, _ = _run(tmp_path)

    with pytest.raises(AppError) as error:
        service.record_evidence(
            run_id, attempt_id="spec-9-abcdef", node="spec.spec", child="spec", payload=PAYLOAD
        )

    assert error.value.code == "attempt_owner_mismatch"
