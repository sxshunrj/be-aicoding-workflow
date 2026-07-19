import pytest

from ai_workflow.errors import AppError
from ai_workflow.workflow.graph import NodeValidity, RunGraphNode, WorkflowProfile
from ai_workflow.workflow.machine import (
    StateMachine,
    earliest_phase,
    effective_phases,
    phase_is_valid,
    phase_nodes,
)
from ai_workflow.workflow.models import Phase, RunState


def new_state() -> RunState:
    graph = {
        "spec.spec": RunGraphNode("spec.spec", Phase.SPEC, "spec"),
        "plan.solution": RunGraphNode("plan.solution", Phase.PLAN, "solution"),
        "plan.test_strategy": RunGraphNode(
            "plan.test_strategy", Phase.PLAN, "test_strategy"
        ),
        "implement.code": RunGraphNode("implement.code", Phase.IMPLEMENT, "code"),
        "verify.build": RunGraphNode("verify.build", Phase.VERIFY, "build"),
        "verify.unit_test": RunGraphNode(
            "verify.unit_test", Phase.VERIFY, "unit_test"
        ),
        "verify.code_review": RunGraphNode(
            "verify.code_review", Phase.VERIFY, "code_review"
        ),
    }
    return RunState.new(
        "RUN-001",
        "abc123",
        "Implement graph",
        WorkflowProfile.FULL,
        graph,
        Phase.SPEC,
    )


def new_grill_state() -> RunState:
    graph = {
        "plan.prd": RunGraphNode("plan.prd", Phase.PLAN, "prd"),
        "implement.code": RunGraphNode("implement.code", Phase.IMPLEMENT, "code"),
        "verify.unit_test": RunGraphNode(
            "verify.unit_test", Phase.VERIFY, "unit_test"
        ),
        "verify.code_review": RunGraphNode(
            "verify.code_review", Phase.VERIFY, "code_review"
        ),
    }
    return RunState.new(
        "RUN-001",
        "abc123",
        "Implement grill graph",
        WorkflowProfile.GRILL,
        graph,
        Phase.PLAN,
    )


def test_phase_helpers_use_effective_run_graph_nodes() -> None:
    state = new_state()
    plan_nodes = phase_nodes(state, Phase.PLAN)

    assert tuple(node.key for node in plan_nodes) == (
        "plan.solution",
        "plan.test_strategy",
    )
    assert not phase_is_valid(state, Phase.PLAN)

    for node in plan_nodes:
        node.validity = NodeValidity.VALID
    assert phase_is_valid(state, Phase.PLAN)


def test_advances_only_after_all_current_phase_nodes_are_valid() -> None:
    state = new_state()
    machine = StateMachine()

    with pytest.raises(AppError, match="current phase is not valid"):
        machine.advance(state)

    state.run_graph["spec.spec"].validity = NodeValidity.VALID
    machine.advance(state)
    assert state.current_phase == Phase.PLAN.value

    state.run_graph["plan.solution"].validity = NodeValidity.VALID
    with pytest.raises(AppError, match="current phase is not valid"):
        machine.advance(state)


def test_rerun_moves_back_and_resets_downstream_phase_nodes() -> None:
    state = new_state()
    for node in state.run_graph.values():
        node.validity = NodeValidity.VALID
    state.current_phase = Phase.VERIFY.value

    StateMachine().apply_reruns(
        state,
        {
            "verify.unit_test": "tests failed",
            "implement.code": "verification found a missing branch",
        },
    )

    assert state.current_phase == Phase.IMPLEMENT.value
    assert state.run_graph["implement.code"].validity is NodeValidity.RERUN
    assert (
        state.run_graph["implement.code"].reason
        == "verification found a missing branch"
    )
    assert state.run_graph["verify.unit_test"].validity is NodeValidity.PENDING
    assert state.run_graph["verify.unit_test"].reason is None
    assert state.run_graph["verify.build"].validity is NodeValidity.PENDING
    assert state.run_graph["plan.solution"].validity is NodeValidity.VALID


def test_single_verify_child_rerun_preserves_valid_siblings() -> None:
    state = new_state()
    for node in state.run_graph.values():
        node.validity = NodeValidity.VALID
    state.current_phase = Phase.VERIFY.value

    StateMachine().apply_reruns(state, {"verify.unit_test": "tests failed"})

    assert state.current_phase == "verify"
    assert state.run_graph["verify.unit_test"].validity is NodeValidity.RERUN
    assert state.run_graph["verify.unit_test"].reason == "tests failed"
    assert state.run_graph["verify.build"].validity is NodeValidity.VALID
    assert state.run_graph["verify.code_review"].validity is NodeValidity.VALID


def test_rerun_preserves_unrequested_sibling_in_earliest_phase() -> None:
    state = new_state()
    for node in state.run_graph.values():
        node.validity = NodeValidity.VALID
    state.current_phase = Phase.VERIFY.value

    StateMachine().apply_reruns(
        state, {"plan.test_strategy": "acceptance criteria changed"}
    )

    assert state.run_graph["plan.solution"].validity is NodeValidity.VALID
    assert state.run_graph["plan.test_strategy"].validity is NodeValidity.RERUN
    assert state.run_graph["implement.code"].validity is NodeValidity.PENDING


def test_full_spec_rerun_clears_all_downstream_nodes() -> None:
    state = new_state()
    for node in state.run_graph.values():
        node.validity = NodeValidity.VALID
    state.current_phase = Phase.VERIFY.value

    StateMachine().apply_reruns(state, {"spec.spec": "requirement changed"})

    assert state.current_phase == "spec"
    assert state.run_graph["spec.spec"].validity is NodeValidity.RERUN
    for key, node in state.run_graph.items():
        if key != "spec.spec":
            assert node.validity is NodeValidity.PENDING
            assert node.reason is None


def test_effective_phases_and_advance_skip_absent_grill_spec() -> None:
    state = new_grill_state()
    machine = StateMachine()

    assert effective_phases(state) == (Phase.PLAN, Phase.IMPLEMENT, Phase.VERIFY)
    assert state.current_phase == "plan"
    state.run_graph["plan.prd"].validity = NodeValidity.VALID
    machine.advance(state)
    assert state.current_phase == "implement"
    state.run_graph["implement.code"].validity = NodeValidity.VALID
    machine.advance(state)
    assert state.current_phase == "verify"


def test_grill_plan_prd_rerun_clears_implement_and_verify() -> None:
    state = new_grill_state()
    for node in state.run_graph.values():
        node.validity = NodeValidity.VALID
    state.current_phase = Phase.VERIFY.value

    StateMachine().apply_reruns(state, {"plan.prd": "acceptance criteria changed"})

    assert state.current_phase == "plan"
    assert state.run_graph["plan.prd"].validity is NodeValidity.RERUN
    for key in ("implement.code", "verify.unit_test", "verify.code_review"):
        assert state.run_graph[key].validity is NodeValidity.PENDING
        assert state.run_graph[key].reason is None


def test_rejects_empty_rerun_reason() -> None:
    state = new_state()
    state.current_phase = Phase.PLAN.value

    with pytest.raises(AppError, match="reason must not be empty"):
        StateMachine().apply_reruns(state, {"plan.solution": "  "})


def test_rejects_unknown_rerun_node() -> None:
    state = new_state()
    state.current_phase = Phase.IMPLEMENT.value

    with pytest.raises(AppError, match="unknown rerun node"):
        StateMachine().apply_reruns(state, {"implement.unknown": "missing"})


def test_rejects_rerun_of_a_forward_node() -> None:
    state = new_state()
    state.current_phase = Phase.IMPLEMENT.value

    with pytest.raises(AppError, match="forward phase"):
        StateMachine().apply_reruns(state, {"verify.unit_test": "not reached"})


def test_earliest_phase_requires_at_least_one_node() -> None:
    with pytest.raises(AppError, match="at least one rerun node is required"):
        earliest_phase([])


@pytest.mark.parametrize("status", ["blocked", "aborted", "completed"])
def test_rejects_rerun_for_non_active_run(status: str) -> None:
    state = new_state()
    state.status = status

    with pytest.raises(AppError):
        StateMachine().apply_reruns(state, {"spec.spec": "new requirement"})


@pytest.mark.parametrize("status", ["blocked", "aborted", "completed"])
def test_rejects_advance_for_non_active_run(status: str) -> None:
    state = new_state()
    state.status = status
    state.run_graph["spec.spec"].validity = NodeValidity.VALID

    with pytest.raises(AppError):
        StateMachine().advance(state)
