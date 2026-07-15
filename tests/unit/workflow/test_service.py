from datetime import datetime
import hashlib
from pathlib import Path
import shutil

import pytest
import yaml

from ai_workflow.errors import AppError
from ai_workflow.contracts.artifacts import ArtifactRef, ChildResult, Finding
from ai_workflow.contracts.packets import DispatchPacket
from ai_workflow.workflow.graph import NodeValidity
from ai_workflow.workflow.models import Phase
from ai_workflow.workflow.service import WorkflowService
from ai_workflow.workflow.store import Event, StateStore


def _config(repo: Path, max_attempts: int = 3) -> None:
    (repo / ".ai-workflow.yaml").write_text(
        f"repository: demo\nmax_attempts: {max_attempts}\n", encoding="utf-8"
    )


def _skill_dir(repo: Path) -> Path:
    contracts = repo / "skill" / "references" / "agents"
    contracts.mkdir(parents=True, exist_ok=True)
    for name in (
        "common-phase-contract.md",
        "spec-writer.md",
        "planner.md",
        "coder.md",
        "test-runner.md",
        "code-reviewer.md",
    ):
        (contracts / name).write_text(f"# {name}\n", encoding="utf-8")
    return contracts.parents[1]


def _finalize_phase(
    service: WorkflowService,
    repo: Path,
    run_id: str,
    phase: Phase,
    *,
    unable_child: str | None = None,
):
    attempt = service.begin(run_id, phase, _skill_dir(repo))
    for item in attempt.dispatch_plan:
        assert item.packet_file is not None
        packet = DispatchPacket.load(item.packet_file)
        artifact = None
        status = "unable_to_complete" if item.child == unable_child else "completed"
        if status == "completed":
            artifact_path = repo / packet.allowed_output_path
            artifact_path.parent.mkdir(parents=True, exist_ok=True)
            artifact_path.write_text(f"# {item.node}\n", encoding="utf-8")
            artifact = ArtifactRef(
                packet.allowed_output_path,
                hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
                2,
                phase,
                item.child,
                "abc123",
            )
        result_path = repo / f"{phase.value}-{item.child}-result.json"
        ChildResult(
            run_id,
            phase,
            item.child,
            attempt.attempt_id,
            packet.execution_mode,
            status,
            "child result",
            artifact,
            (),
        ).write(result_path)
        service.stage(run_id, attempt.attempt_id, item.child, result_path)
    service.finalize(run_id, attempt.attempt_id)
    return attempt


def _review_transition(
    service: WorkflowService,
    run_id: str,
    reruns: dict[str, str] | None = None,
):
    decision = service.review(run_id, reruns or {})
    if decision.decision == "human_review":
        service.record_review_acceptance(run_id, decision.digest)
    return service.transition(run_id)


def test_init_uses_injected_clock_and_id_factory(tmp_path: Path) -> None:
    _config(tmp_path)
    service = WorkflowService(
        clock=lambda: datetime(2026, 7, 14, 12, 34, 56),
        id_factory=lambda: "a1b2c3",
    )

    state = service.init(tmp_path, "abc123", "Test workflow service")

    assert state.run_id == "RUN-20260714-123456-a1b2c3"


def test_begin_rejects_attempt_over_repository_limit(tmp_path: Path) -> None:
    _config(tmp_path, max_attempts=1)
    service = WorkflowService(tmp_path, id_factory=lambda: "a1b2c3")
    state = service.init(tmp_path, "abc123", "Test attempt limits")
    service.begin(state.run_id, Phase.SPEC, _skill_dir(tmp_path))
    persisted = service.status(state.run_id)
    persisted.artifacts["current_attempts"] = {}
    persisted.run_graph["spec.spec"].validity = NodeValidity.RERUN
    persisted.run_graph["spec.spec"].reason = "try again"
    StateStore(service._store(state.run_id).run_dir).save(
        persisted.version,
        persisted,
        Event("test_attempt_released", {}),
    )

    with pytest.raises(AppError, match="maximum attempts"):
        service.begin(state.run_id, Phase.SPEC, _skill_dir(tmp_path))


@pytest.mark.parametrize("suffix", ["abc12", "ABCDEF", "gggggg", "abcdef0", "../bad"])
def test_init_rejects_invalid_id_suffix(tmp_path: Path, suffix: str) -> None:
    _config(tmp_path)
    service = WorkflowService(tmp_path, id_factory=lambda: suffix)

    with pytest.raises(AppError, match="ID suffix"):
        service.init(tmp_path, "abc123", "Test invalid ID")


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
    state = service.init(tmp_path, "abc123", "Test blocking")
    if begin_first:
        service.begin(state.run_id, Phase.SPEC, _skill_dir(tmp_path))

    service.block(state.run_id, "waiting")
    blocked = service.status(state.run_id)
    resumed = service.resume(state.run_id)

    assert blocked.artifacts["_blocked_state"] == {
        "run": expected,
        "phase": "spec",
    }
    assert resumed.status == expected
    assert resumed.run_graph["spec.spec"].validity is NodeValidity.PENDING


def test_resume_can_apply_actionable_node_reruns(tmp_path: Path) -> None:
    _config(tmp_path)
    service = WorkflowService(tmp_path, id_factory=lambda: "abcdef")
    state = service.init(tmp_path, "abc123", "Test blocked reruns")
    _finalize_phase(service, tmp_path, state.run_id, Phase.SPEC)
    state = _review_transition(service, state.run_id)
    service.begin(state.run_id, Phase.PLAN, _skill_dir(tmp_path))
    service.block(state.run_id, "waiting for corrected requirements")

    resumed = service.resume(
        state.run_id, {"spec.spec": "requirements changed after review"}
    )

    assert resumed.status == "pending"
    assert resumed.current_phase == "spec"
    assert resumed.run_graph["spec.spec"].validity is NodeValidity.RERUN
    assert (
        resumed.run_graph["spec.spec"].reason
        == "requirements changed after review"
    )
    assert "plan" not in resumed.artifacts["current_attempts"]


def test_blocked_run_can_be_aborted_but_cannot_be_reviewed(tmp_path: Path) -> None:
    _config(tmp_path)
    service = WorkflowService(tmp_path, id_factory=lambda: "abcdef")
    state = service.init(tmp_path, "abc123", "Test blocked abort")
    service.block(state.run_id, "human decision required")

    with pytest.raises(AppError, match="blocked run"):
        service.review(state.run_id, {})

    aborted = service.abort(state.run_id)
    assert aborted.status == "aborted"
    assert "_blocked_state" not in aborted.artifacts

    with pytest.raises(AppError, match="terminal run"):
        service.review(state.run_id, {})


def test_verify_can_rerun_implement_then_return_to_verify(tmp_path: Path) -> None:
    _config(tmp_path)
    service = WorkflowService(tmp_path, id_factory=lambda: "abcdef")
    state = service.init(tmp_path, "abc123", "Test reruns")
    for phase in (Phase.SPEC, Phase.PLAN, Phase.IMPLEMENT):
        _finalize_phase(service, tmp_path, state.run_id, phase)
        state = _review_transition(service, state.run_id)
    _finalize_phase(service, tmp_path, state.run_id, Phase.VERIFY)

    state = _review_transition(
        service,
        state.run_id,
        {"implement.code": "missing branch"},
    )
    assert state.run_graph["verify.code_review"].validity is NodeValidity.PENDING
    _finalize_phase(service, tmp_path, state.run_id, Phase.IMPLEMENT)
    state = _review_transition(service, state.run_id)
    attempt = service.begin(state.run_id, Phase.VERIFY, _skill_dir(tmp_path))

    assert attempt.number == 2


def test_failed_submission_can_be_followed_by_rerun_transition(tmp_path: Path) -> None:
    _config(tmp_path)
    service = WorkflowService(tmp_path, id_factory=lambda: "abcdef")
    state = service.init(tmp_path, "abc123", "Test unable result")
    for phase in (Phase.SPEC, Phase.PLAN, Phase.IMPLEMENT):
        _finalize_phase(service, tmp_path, state.run_id, phase)
        state = _review_transition(service, state.run_id)
    _finalize_phase(
        service,
        tmp_path,
        state.run_id,
        Phase.VERIFY,
        unable_child="code_review",
    )
    state = service.status(state.run_id)
    assert state.status == "running"
    assert state.current_phase == "verify"

    state = _review_transition(
        service,
        state.run_id,
        {
            "implement.code": "missing branch",
            "verify.code_review": "repeat review after implementing the branch",
        },
    )
    assert state.current_phase == "implement"


def test_rerun_transition_requires_a_started_attempt(tmp_path: Path) -> None:
    _config(tmp_path)
    service = WorkflowService(tmp_path, id_factory=lambda: "abcdef")
    state = service.init(tmp_path, "abc123", "Test transition guard")

    with pytest.raises(AppError, match="must be finalized"):
        service.review(state.run_id, {"spec.spec": "retry"})
    with pytest.raises(AppError, match="must be finalized"):
        service.transition(state.run_id)


def test_status_rejects_symlinked_run_directory(tmp_path: Path) -> None:
    _config(tmp_path)
    service = WorkflowService(tmp_path, id_factory=lambda: "bbbbbb")
    target = service.init(tmp_path, "abc123", "Test symlink guard")
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
    target = service.init(tmp_path, "abc123", "Test symlink mutation guard")
    alias = "RUN-20260714-123456-aaaaaa"
    (tmp_path / ".ai-workflow" / "runs" / alias).symlink_to(
        tmp_path / ".ai-workflow" / "runs" / target.run_id,
        target_is_directory=True,
    )

    with pytest.raises(AppError, match="symlink"):
        service.begin(alias, Phase.SPEC, _skill_dir(tmp_path))


def test_load_rejects_state_run_id_mismatch(tmp_path: Path) -> None:
    _config(tmp_path)
    service = WorkflowService(tmp_path, id_factory=lambda: "bbbbbb")
    target = service.init(tmp_path, "abc123", "Test run ID ownership")
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
        lambda data: data["run_graph"].pop("spec.spec"),
        lambda data: data["artifacts"].update(attempts={"spec": "many"}),
    ],
    ids=["invalid-current-phase", "missing-current-node", "nonnumeric-attempt"],
)
def test_load_rejects_semantically_invalid_state(
    tmp_path: Path, mutation
) -> None:
    _config(tmp_path)
    service = WorkflowService(tmp_path, id_factory=lambda: "abcdef")
    state = service.init(tmp_path, "abc123", "Test state validation")
    state_path = tmp_path / ".ai-workflow" / "runs" / state.run_id / "state.yaml"
    data = yaml.safe_load(state_path.read_text(encoding="utf-8"))
    mutation(data)
    state_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    with pytest.raises(AppError) as error:
        service.status(state.run_id)

    assert error.value.code in {"invalid_state", "invalid_run_graph"}


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
    state = service.init(tmp_path, "abc123", "Test metadata validation")
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
    state = service.init(tmp_path, "abc123", "Test legacy metadata rejection")
    attempt = service.begin(state.run_id, Phase.SPEC, _skill_dir(tmp_path))
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
