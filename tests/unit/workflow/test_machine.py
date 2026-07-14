import pytest

from ai_workflow.errors import AppError
from ai_workflow.workflow.machine import StateMachine
from ai_workflow.workflow.models import Phase, RunState


def test_advances_only_after_current_node_is_valid() -> None:
    state = RunState.new("RUN-001", "abc123")
    machine = StateMachine()

    with pytest.raises(AppError, match="current node is not valid"):
        machine.advance(state)

    state.nodes[Phase.SPEC.value].status = "valid"
    machine.advance(state)
    assert state.current_phase == Phase.PLAN.value


def test_rerun_moves_back_to_earliest_invalid_phase() -> None:
    state = RunState.new("RUN-001", "abc123")
    for node in state.nodes.values():
        node.status = "valid"
    state.current_phase = Phase.VERIFY.value
    machine = StateMachine()
    machine.apply_reruns(
        state,
        {
            Phase.VERIFY: "verification failed",
            Phase.IMPLEMENT: "verification found missing branch",
        },
    )

    assert state.current_phase == Phase.IMPLEMENT.value
    assert state.nodes["implement"].status == "rerun"


def test_rejects_empty_rerun_reason() -> None:
    state = RunState.new("RUN-001", "abc123")
    state.current_phase = Phase.PLAN.value

    with pytest.raises(AppError, match="reason must not be empty"):
        StateMachine().apply_reruns(state, {Phase.PLAN: "  "})


def test_rejects_rerun_of_a_forward_phase() -> None:
    state = RunState.new("RUN-001", "abc123")
    state.current_phase = Phase.IMPLEMENT.value

    with pytest.raises(AppError, match="forward phase"):
        StateMachine().apply_reruns(state, {Phase.VERIFY: "not reached"})


def test_rerun_resets_downstream_nodes() -> None:
    state = RunState.new("RUN-001", "abc123")
    state.current_phase = Phase.VERIFY.value
    for node in state.nodes.values():
        node.status = "valid"

    StateMachine().apply_reruns(state, {Phase.IMPLEMENT: "missing branch"})

    assert state.nodes["implement"].status == "rerun"
    assert state.nodes["verify"].status == "pending"


@pytest.mark.parametrize("status", ["blocked", "aborted", "completed"])
def test_rejects_advance_for_non_active_run(status: str) -> None:
    state = RunState.new("RUN-001", "abc123")
    state.status = status
    state.nodes["spec"].status = "valid"

    with pytest.raises(AppError):
        StateMachine().advance(state)
