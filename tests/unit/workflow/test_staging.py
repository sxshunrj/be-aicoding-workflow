import hashlib
import json
from pathlib import Path

import pytest
import yaml

from ai_workflow.contracts.artifacts import ArtifactRef, ChildResult
from ai_workflow.contracts.packets import DispatchPacket
from ai_workflow.errors import AppError
from ai_workflow.workflow.graph import NodeValidity
from ai_workflow.workflow.models import Phase
from ai_workflow.workflow.service import WorkflowService
from ai_workflow.workflow.store import Event, StateStore


def _config(repo: Path, *, protected_paths: tuple[str, ...] = ()) -> None:
    protected = ""
    if protected_paths:
        protected = f"protected_paths: [{', '.join(protected_paths)}]\n"
    (repo / ".ai-workflow.yaml").write_text(
        "repository: demo\n"
        "commands:\n"
        "  unit_test: [pytest, -q]\n"
        f"{protected}",
        encoding="utf-8",
    )


def _skill_dir(root: Path) -> Path:
    skill_dir = root / "skill"
    contracts = skill_dir / "references" / "agents"
    contracts.mkdir(parents=True)
    for name in (
        "common-phase-contract.md",
        "spec-writer.md",
        "planner.md",
        "coder.md",
        "test-runner.md",
        "code-reviewer.md",
    ):
        (contracts / name).write_text(f"# {name}\n", encoding="utf-8")
    return skill_dir


def _service(tmp_path: Path, *, protected_paths: tuple[str, ...] = ()):
    _config(tmp_path, protected_paths=protected_paths)
    service = WorkflowService(tmp_path, id_factory=lambda: "abcdef")
    run = service.init(tmp_path, "abc123", "Design the workflow")
    return service, run, _skill_dir(tmp_path)


def _set_current_phase(service: WorkflowService, run_id: str, phase: Phase) -> None:
    state = service.status(run_id)
    for node in state.run_graph.values():
        if list(Phase).index(node.phase) < list(Phase).index(phase):
            node.validity = NodeValidity.VALID
            node.reason = None
    state.current_phase = phase.value
    StateStore(service._store(run_id).run_dir).save(
        state.version, state, Event("test_phase_selected", {"phase": phase.value})
    )


def _result(
    repo: Path,
    run_id: str,
    attempt_id: str,
    phase: Phase,
    child: str,
    *,
    status: str = "completed",
    citations: tuple[str, ...] = (),
    output_path: str | None = None,
    summary: str = "completed",
) -> Path:
    artifact = None
    if status == "completed":
        owned_path = output_path or f"artifacts/{phase.value}-{child.replace('_', '-')}.md"
        path = repo / owned_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {phase.value}.{child}\n", encoding="utf-8")
        artifact = ArtifactRef(
            path=owned_path,
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            schema_version=2,
            phase=phase,
            child=child,
            source_revision="abc123",
        )
    result = ChildResult(
        run_id=run_id,
        phase=phase,
        child=child,
        attempt_id=attempt_id,
        execution_mode="fresh",
        status=status,  # type: ignore[arg-type]
        summary=summary,
        artifact=artifact,
        findings=(),
        knowledge_citations=citations,
    )
    result_path = repo / f"{child}-result.json"
    result.write(result_path)
    return result_path


def test_plan_children_stage_behind_barrier_and_finalize_without_advancing(
    tmp_path: Path,
) -> None:
    service, run, skill_dir = _service(tmp_path)
    _set_current_phase(service, run.run_id, Phase.PLAN)
    attempt = service.begin(run.run_id, Phase.PLAN, skill_dir)

    assert {item.child for item in attempt.dispatch_plan} == {
        "solution",
        "test_strategy",
    }
    assert all(item.action == "dispatch" for item in attempt.dispatch_plan)

    solution = _result(
        tmp_path, run.run_id, attempt.attempt_id, Phase.PLAN, "solution"
    )
    strategy = _result(
        tmp_path, run.run_id, attempt.attempt_id, Phase.PLAN, "test_strategy"
    )
    service.stage(run.run_id, attempt.attempt_id, "solution", solution)

    with pytest.raises(AppError, match="missing child result"):
        service.finalize(run.run_id, attempt.attempt_id)

    service.stage(run.run_id, attempt.attempt_id, "test_strategy", strategy)
    aggregate = service.finalize(run.run_id, attempt.attempt_id)

    assert aggregate.status == "completed"
    assert {child["child"] for child in aggregate.children} == {
        "solution",
        "test_strategy",
    }
    state = service.status(run.run_id)
    assert state.current_phase == "plan"
    assert state.run_graph["plan.solution"].validity is NodeValidity.VALID
    assert state.run_graph["plan.test_strategy"].validity is NodeValidity.VALID


def test_begin_writes_per_child_dispatch_packets_prompts_and_knowledge(
    tmp_path: Path,
) -> None:
    service, run, skill_dir = _service(tmp_path)
    _set_current_phase(service, run.run_id, Phase.PLAN)

    attempt = service.begin(run.run_id, Phase.PLAN, skill_dir)

    for item in attempt.dispatch_plan:
        assert item.prompt_file is not None and Path(item.prompt_file).is_file()
        assert item.packet_file is not None and Path(item.packet_file).is_file()
        packet = DispatchPacket.load(item.packet_file)
        assert packet.child == item.child
        assert packet.requirement == "Design the workflow"
        assert Path(packet.knowledge_packet["path"]).is_file()
        assert packet.allowed_output_path == (
            f"artifacts/plan-{item.child.replace('_', '-')}.md"
        )


def test_begin_reuses_current_attempt_and_marks_staged_child(tmp_path: Path) -> None:
    service, run, skill_dir = _service(tmp_path)
    _set_current_phase(service, run.run_id, Phase.PLAN)
    first = service.begin(run.run_id, Phase.PLAN, skill_dir)
    result = _result(
        tmp_path, run.run_id, first.attempt_id, Phase.PLAN, "solution"
    )
    service.stage(run.run_id, first.attempt_id, "solution", result)

    resumed = service.begin(run.run_id, Phase.PLAN, skill_dir)

    assert resumed.attempt_id == first.attempt_id
    assert resumed.number == first.number
    actions = {item.child: item for item in resumed.dispatch_plan}
    assert actions["solution"].action == "already_staged"
    assert actions["solution"].prompt_file is None
    assert actions["solution"].packet_file is None
    assert actions["test_strategy"].action == "dispatch"


def test_begin_rejects_tampered_current_dispatch_prompt(tmp_path: Path) -> None:
    service, run, skill_dir = _service(tmp_path)
    attempt = service.begin(run.run_id, Phase.SPEC, skill_dir)
    prompt = Path(attempt.dispatch_plan[0].prompt_file)
    prompt.write_text("tampered\n", encoding="utf-8")

    with pytest.raises(AppError, match="dispatch prompt"):
        service.begin(run.run_id, Phase.SPEC, skill_dir)


def test_stage_rejects_wrong_child_result_and_stale_attempt(tmp_path: Path) -> None:
    service, run, skill_dir = _service(tmp_path)
    attempt = service.begin(run.run_id, Phase.SPEC, skill_dir)
    wrong_child = _result(
        tmp_path, run.run_id, attempt.attempt_id, Phase.SPEC, "other"
    )

    with pytest.raises(AppError, match="child"):
        service.stage(run.run_id, attempt.attempt_id, "spec", wrong_child)
    with pytest.raises(AppError, match="attempt"):
        service.stage(run.run_id, "spec-2-abcdef", "spec", wrong_child)


@pytest.mark.parametrize("operation", ["stage", "finalize"])
def test_blocked_run_rejects_staging_and_finalization(
    tmp_path: Path, operation: str
) -> None:
    service, run, skill_dir = _service(tmp_path)
    attempt = service.begin(run.run_id, Phase.SPEC, skill_dir)
    result = _result(
        tmp_path, run.run_id, attempt.attempt_id, Phase.SPEC, "spec"
    )
    if operation == "finalize":
        service.stage(run.run_id, attempt.attempt_id, "spec", result)
    service.block(run.run_id, "wait for user input")

    with pytest.raises(AppError, match="blocked run"):
        if operation == "stage":
            service.stage(run.run_id, attempt.attempt_id, "spec", result)
        else:
            service.finalize(run.run_id, attempt.attempt_id)


def test_aborted_run_rejects_staging(tmp_path: Path) -> None:
    service, run, skill_dir = _service(tmp_path)
    attempt = service.begin(run.run_id, Phase.SPEC, skill_dir)
    result = _result(
        tmp_path, run.run_id, attempt.attempt_id, Phase.SPEC, "spec"
    )
    service.abort(run.run_id)

    with pytest.raises(AppError, match="terminal run"):
        service.stage(run.run_id, attempt.attempt_id, "spec", result)


def test_stage_rejects_unknown_citation(tmp_path: Path) -> None:
    service, run, skill_dir = _service(tmp_path)
    attempt = service.begin(run.run_id, Phase.SPEC, skill_dir)
    result = _result(
        tmp_path,
        run.run_id,
        attempt.attempt_id,
        Phase.SPEC,
        "spec",
        citations=("KW-missing-001",),
    )

    with pytest.raises(AppError, match="not in phase packet"):
        service.stage(run.run_id, attempt.attempt_id, "spec", result)


def test_stage_rejects_dispatch_packet_owned_by_another_requirement(
    tmp_path: Path,
) -> None:
    service, run, skill_dir = _service(tmp_path)
    attempt = service.begin(run.run_id, Phase.SPEC, skill_dir)
    packet_path = Path(attempt.dispatch_plan[0].packet_file)
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    packet["requirement"] = "A different run requirement"
    packet_path.write_text(json.dumps(packet), encoding="utf-8")
    result = _result(
        tmp_path, run.run_id, attempt.attempt_id, Phase.SPEC, "spec"
    )

    with pytest.raises(AppError, match="dispatch packet ownership"):
        service.stage(run.run_id, attempt.attempt_id, "spec", result)


def test_stage_accepts_unable_result_with_owned_diagnostic_artifact(
    tmp_path: Path,
) -> None:
    service, run, skill_dir = _service(tmp_path)
    attempt = service.begin(run.run_id, Phase.SPEC, skill_dir)
    artifact_path = tmp_path / "artifacts" / "spec-spec.md"
    artifact_path.parent.mkdir()
    artifact_path.write_text("diagnostic evidence\n", encoding="utf-8")
    result_path = tmp_path / "unable-result.json"
    ChildResult(
        run_id=run.run_id,
        phase=Phase.SPEC,
        child="spec",
        attempt_id=attempt.attempt_id,
        execution_mode="fresh",
        status="unable_to_complete",
        summary="diagnostic evidence captured",
        artifact=ArtifactRef(
            "artifacts/spec-spec.md",
            hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
            2,
            Phase.SPEC,
            "spec",
            "abc123",
        ),
        findings=(),
    ).write(result_path)

    service.stage(run.run_id, attempt.attempt_id, "spec", result_path)

    assert service.status(run.run_id).status == "running"


def test_stage_rejects_protected_artifact_path(tmp_path: Path) -> None:
    service, run, skill_dir = _service(tmp_path, protected_paths=("artifacts/**",))
    attempt = service.begin(run.run_id, Phase.SPEC, skill_dir)
    result = _result(
        tmp_path, run.run_id, attempt.attempt_id, Phase.SPEC, "spec"
    )

    with pytest.raises(AppError, match="protected"):
        service.stage(run.run_id, attempt.attempt_id, "spec", result)


def test_stage_rejects_artifact_outside_child_owned_output(tmp_path: Path) -> None:
    service, run, skill_dir = _service(tmp_path)
    attempt = service.begin(run.run_id, Phase.SPEC, skill_dir)
    result = _result(
        tmp_path,
        run.run_id,
        attempt.attempt_id,
        Phase.SPEC,
        "spec",
        output_path="outside-owned-output.md",
    )

    with pytest.raises(AppError, match="owned output"):
        service.stage(run.run_id, attempt.attempt_id, "spec", result)


def test_stage_rejects_symlinked_staging_directory(tmp_path: Path) -> None:
    service, run, skill_dir = _service(tmp_path)
    attempt = service.begin(run.run_id, Phase.SPEC, skill_dir)
    attempt_dir = service._store(run.run_id).attempt_dir(attempt.attempt_id)
    outside = tmp_path / "outside-staged"
    outside.mkdir()
    (attempt_dir / "staged").symlink_to(outside, target_is_directory=True)
    result = _result(
        tmp_path, run.run_id, attempt.attempt_id, Phase.SPEC, "spec"
    )

    with pytest.raises(AppError, match="symlink"):
        service.stage(run.run_id, attempt.attempt_id, "spec", result)


def test_finalize_marks_only_unable_child_for_rerun(tmp_path: Path) -> None:
    service, run, skill_dir = _service(tmp_path)
    _set_current_phase(service, run.run_id, Phase.PLAN)
    attempt = service.begin(run.run_id, Phase.PLAN, skill_dir)
    completed = _result(
        tmp_path, run.run_id, attempt.attempt_id, Phase.PLAN, "solution"
    )
    unable = _result(
        tmp_path,
        run.run_id,
        attempt.attempt_id,
        Phase.PLAN,
        "test_strategy",
        status="unable_to_complete",
        summary="Could not derive a runnable strategy",
    )
    service.stage(run.run_id, attempt.attempt_id, "solution", completed)
    service.stage(run.run_id, attempt.attempt_id, "test_strategy", unable)

    aggregate = service.finalize(run.run_id, attempt.attempt_id)

    state = service.status(run.run_id)
    assert aggregate.status == "unable_to_complete"
    assert state.run_graph["plan.solution"].validity is NodeValidity.VALID
    failed = state.run_graph["plan.test_strategy"]
    assert failed.validity is NodeValidity.RERUN
    assert failed.reason == (
        "child unable to complete; workflow must provide an actionable reason"
    )


def test_finalize_is_idempotent_and_persists_one_immutable_aggregate(
    tmp_path: Path,
) -> None:
    service, run, skill_dir = _service(tmp_path)
    attempt = service.begin(run.run_id, Phase.SPEC, skill_dir)
    result = _result(
        tmp_path, run.run_id, attempt.attempt_id, Phase.SPEC, "spec"
    )
    service.stage(run.run_id, attempt.attempt_id, "spec", result)

    first = service.finalize(run.run_id, attempt.attempt_id)
    first_version = service.status(run.run_id).version
    aggregate_path = service._store(run.run_id).aggregate_path(attempt.attempt_id)
    original = aggregate_path.read_bytes()
    second = service.finalize(run.run_id, attempt.attempt_id)
    events = [
        json.loads(line)
        for line in service._store(run.run_id).events_path.read_text().splitlines()
    ]

    assert second == first
    assert service.status(run.run_id).version == first_version
    assert aggregate_path.read_bytes() == original
    assert sum(event["type"] == "phase_finalized" for event in events) == 1


def test_status_rejects_aggregate_phase_that_does_not_match_attempt(
    tmp_path: Path,
) -> None:
    service, run, skill_dir = _service(tmp_path)
    attempt = service.begin(run.run_id, Phase.SPEC, skill_dir)
    result = _result(
        tmp_path, run.run_id, attempt.attempt_id, Phase.SPEC, "spec"
    )
    service.stage(run.run_id, attempt.attempt_id, "spec", result)
    service.finalize(run.run_id, attempt.attempt_id)
    state_path = service._store(run.run_id).state_path
    state = yaml.safe_load(state_path.read_text(encoding="utf-8"))
    state["artifacts"]["phase_aggregates"][attempt.attempt_id]["phase"] = "plan"
    state_path.write_text(yaml.safe_dump(state, sort_keys=False), encoding="utf-8")

    with pytest.raises(AppError, match="phase aggregate metadata"):
        service.status(run.run_id)
