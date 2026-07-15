from datetime import datetime
import hashlib
from pathlib import Path
import shutil

import pytest
import yaml

from ai_workflow.errors import AppError
from ai_workflow.contracts.artifacts import ArtifactRef, ChildResult, Finding
from ai_workflow.workflow.models import Phase
from ai_workflow.workflow.service import WorkflowService


def _config(repo: Path, max_attempts: int = 3) -> None:
    (repo / ".ai-workflow.yaml").write_text(
        f"repository: demo\nmax_attempts: {max_attempts}\n", encoding="utf-8"
    )


def test_init_uses_injected_clock_and_id_factory(tmp_path: Path) -> None:
    _config(tmp_path)
    service = WorkflowService(
        clock=lambda: datetime(2026, 7, 14, 12, 34, 56),
        id_factory=lambda: "a1b2c3",
    )

    state = service.init(tmp_path, "abc123")

    assert state.run_id == "RUN-20260714-123456-a1b2c3"


def test_begin_rejects_attempt_over_repository_limit(tmp_path: Path) -> None:
    _config(tmp_path, max_attempts=1)
    service = WorkflowService(tmp_path, id_factory=lambda: "a1b2c3")
    state = service.init(tmp_path, "abc123")
    service.begin(state.run_id, Phase.SPEC)
    service.transition(state.run_id, False, {Phase.SPEC: "try again"})

    with pytest.raises(AppError, match="maximum attempts"):
        service.begin(state.run_id, Phase.SPEC)


@pytest.mark.parametrize("suffix", ["abc12", "ABCDEF", "gggggg", "abcdef0", "../bad"])
def test_init_rejects_invalid_id_suffix(tmp_path: Path, suffix: str) -> None:
    _config(tmp_path)
    service = WorkflowService(tmp_path, id_factory=lambda: suffix)

    with pytest.raises(AppError, match="ID suffix"):
        service.init(tmp_path, "abc123")


@pytest.mark.parametrize("run_id", ["../outside", "/tmp/outside", "RUN-001"])
def test_rejects_invalid_run_id_before_resolving_store(tmp_path: Path, run_id: str) -> None:
    _config(tmp_path)

    with pytest.raises(AppError, match="run ID"):
        WorkflowService(tmp_path).status(run_id)


@pytest.mark.parametrize(
    ("begin_first", "expected"), [(False, "pending"), (True, "running")]
)
def test_resume_restores_prior_lifecycle_state(
    tmp_path: Path, begin_first: bool, expected: str
) -> None:
    _config(tmp_path)
    service = WorkflowService(tmp_path, id_factory=lambda: "abcdef")
    state = service.init(tmp_path, "abc123")
    if begin_first:
        service.begin(state.run_id, Phase.SPEC)

    service.block(state.run_id, "waiting")
    resumed = service.resume(state.run_id)

    assert resumed.status == expected
    assert resumed.nodes["spec"].status == expected


def test_verify_can_rerun_implement_then_return_to_verify(tmp_path: Path) -> None:
    _config(tmp_path)
    service = WorkflowService(tmp_path, id_factory=lambda: "abcdef")
    state = service.init(tmp_path, "abc123")
    for phase in (Phase.SPEC, Phase.PLAN, Phase.IMPLEMENT):
        service.begin(state.run_id, phase)
        state = service.transition(state.run_id, True, {})
    service.begin(state.run_id, Phase.VERIFY)

    state = service.transition(
        state.run_id, False, {Phase.IMPLEMENT: "missing branch"}
    )
    assert state.nodes["verify"].status == "pending"
    service.begin(state.run_id, Phase.IMPLEMENT)
    state = service.transition(state.run_id, True, {})
    attempt = service.begin(state.run_id, Phase.VERIFY)

    assert attempt.number == 2


def test_failed_submission_can_be_followed_by_rerun_transition(tmp_path: Path) -> None:
    _config(tmp_path)
    service = WorkflowService(tmp_path, id_factory=lambda: "abcdef")
    state = service.init(tmp_path, "abc123")
    for phase in (Phase.SPEC, Phase.PLAN, Phase.IMPLEMENT):
        service.begin(state.run_id, phase)
        state = service.transition(state.run_id, True, {})
    attempt = service.begin(state.run_id, Phase.VERIFY)
    attempt_dir = tmp_path / ".ai-workflow" / "runs" / state.run_id / "attempts" / attempt.attempt_id
    artifact_path = attempt_dir / "verify.md"
    artifact_path.write_text("# Verify\n", encoding="utf-8")
    result_path = attempt_dir / "verify-result.json"
    ChildResult(
        "unable_to_complete",
        "blocked",
        ArtifactRef(
            "verify.md",
            hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
            1,
            Phase.VERIFY,
            "abc123",
        ),
        (Finding("verify-gap", "Missing retry branch", "missing retry branch"),),
    ).write(result_path)

    state = service.submit(state.run_id, attempt.attempt_id, result_path)
    assert state.status == "running"
    assert state.current_phase == "verify"

    state = service.transition(state.run_id, False, {Phase.IMPLEMENT: "missing branch"})
    assert state.current_phase == "implement"


def test_rerun_transition_requires_a_started_attempt(tmp_path: Path) -> None:
    _config(tmp_path)
    service = WorkflowService(tmp_path, id_factory=lambda: "abcdef")
    state = service.init(tmp_path, "abc123")

    with pytest.raises(AppError, match="current node is not running"):
        service.transition(state.run_id, False, {Phase.SPEC: "retry"})


def test_status_rejects_symlinked_run_directory(tmp_path: Path) -> None:
    _config(tmp_path)
    service = WorkflowService(tmp_path, id_factory=lambda: "bbbbbb")
    target = service.init(tmp_path, "abc123")
    alias = "RUN-20260714-123456-aaaaaa"
    (tmp_path / ".ai-workflow" / "runs" / alias).symlink_to(
        tmp_path / ".ai-workflow" / "runs" / target.run_id,
        target_is_directory=True,
    )

    with pytest.raises(AppError, match="symlink"):
        service.status(alias)


def test_mutation_rejects_symlinked_run_directory(tmp_path: Path) -> None:
    _config(tmp_path)
    service = WorkflowService(tmp_path, id_factory=lambda: "bbbbbb")
    target = service.init(tmp_path, "abc123")
    alias = "RUN-20260714-123456-aaaaaa"
    (tmp_path / ".ai-workflow" / "runs" / alias).symlink_to(
        tmp_path / ".ai-workflow" / "runs" / target.run_id,
        target_is_directory=True,
    )

    with pytest.raises(AppError, match="symlink"):
        service.begin(alias, Phase.SPEC)


def test_load_rejects_state_run_id_mismatch(tmp_path: Path) -> None:
    _config(tmp_path)
    service = WorkflowService(tmp_path, id_factory=lambda: "bbbbbb")
    target = service.init(tmp_path, "abc123")
    alias = "RUN-20260714-123456-aaaaaa"
    shutil.copytree(
        tmp_path / ".ai-workflow" / "runs" / target.run_id,
        tmp_path / ".ai-workflow" / "runs" / alias,
    )

    with pytest.raises(AppError, match="does not match"):
        service.status(alias)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda data: data.update(current_phase="unknown"),
        lambda data: data["nodes"].pop(data["current_phase"]),
        lambda data: data["artifacts"].update(attempts={"spec": "many"}),
    ],
    ids=["invalid-current-phase", "missing-current-node", "nonnumeric-attempt"],
)
def test_load_rejects_semantically_invalid_state(
    tmp_path: Path, mutation
) -> None:
    _config(tmp_path)
    service = WorkflowService(tmp_path, id_factory=lambda: "abcdef")
    state = service.init(tmp_path, "abc123")
    state_path = tmp_path / ".ai-workflow" / "runs" / state.run_id / "state.yaml"
    data = yaml.safe_load(state_path.read_text(encoding="utf-8"))
    mutation(data)
    state_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    with pytest.raises(AppError) as error:
        service.status(state.run_id)

    assert error.value.code == "invalid_state"


@pytest.mark.parametrize(
    "metadata",
    [
        {"current_attempts": {"unknown": "unknown-1-abcdef"}},
        {"current_attempts": {"spec": "bad"}},
        {"current_attempts": {"spec": "spec-1-abcdef"}},
        {"attempts": {"spec": 1}, "attempt_history": {}},
        {"attempts": {"spec": 1}, "attempt_history": {
            "spec-1-abcdef": {"phase": "spec", "number": 1},
            "spec-1-bbbbbb": {"phase": "spec", "number": 1},
        }},
        {"attempts": {"spec": 2}, "current_attempts": {"spec": "spec-1-abcdef"}},
        {"accepted_results": {"spec-1-abcdef": "not-a-digest"}},
        {"accepted_results": {"spec-1-abcdef": "a" * 64}},
        {"registered": ["not-an-artifact"]},
        {"registered": [{"path": "x", "sha256": "bad", "schema_version": 1,
                          "phase": "spec", "source_revision": "abc123"}]},
        {"registered": [{"path": [], "sha256": "a" * 64, "schema_version": 1,
                          "phase": "spec", "source_revision": "abc123"}]},
        {"rerun_reasons": {"unknown": "reason"}},
        {"rerun_reasons": {"spec": "  "}},
    ],
)
def test_load_rejects_invalid_task4_metadata(tmp_path: Path, metadata) -> None:
    _config(tmp_path)
    service = WorkflowService(tmp_path, id_factory=lambda: "abcdef")
    state = service.init(tmp_path, "abc123")
    state_path = tmp_path / ".ai-workflow" / "runs" / state.run_id / "state.yaml"
    data = yaml.safe_load(state_path.read_text(encoding="utf-8"))
    data["artifacts"].update(metadata)
    state_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    with pytest.raises(AppError) as error:
        service.status(state.run_id)

    assert error.value.code == "invalid_state"


def test_load_rejects_accepted_result_owned_by_another_node(tmp_path: Path) -> None:
    _config(tmp_path)
    service = WorkflowService(tmp_path, id_factory=lambda: "abcdef")
    state = service.init(tmp_path, "abc123")
    attempt = service.begin(state.run_id, Phase.SPEC)
    state_path = tmp_path / ".ai-workflow" / "runs" / state.run_id / "state.yaml"
    data = yaml.safe_load(state_path.read_text(encoding="utf-8"))
    data["artifacts"]["accepted_results"] = {
        attempt.attempt_id: {
            "run_id": state.run_id, "node": "plan", "phase": "plan",
            "attempt_id": attempt.attempt_id, "result_digest": "a" * 64,
            "artifact_digest": None, "accepted_version": data["version"],
            "accepted_at": "2026-07-14T10:00:00", "status": "unable_to_complete",
            "summary": "blocked", "artifact": None,
        }
    }
    state_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    with pytest.raises(AppError) as error:
        service.status(state.run_id)

    assert error.value.code == "invalid_state"
