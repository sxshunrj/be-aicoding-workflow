from ai_workflow.workflow.models import NodeStatus, Phase, RunState


def test_new_run_has_one_pending_node_per_formal_phase() -> None:
    state = RunState.new("RUN-001", "abc123")

    assert state.schema_version == 1
    assert state.version == 0
    assert state.status == NodeStatus.PENDING.value
    assert state.current_phase == Phase.SPEC.value
    assert list(state.nodes) == [phase.value for phase in Phase]
    assert all(node.status == NodeStatus.PENDING.value for node in state.nodes.values())
    assert state.artifacts == {}


def test_run_state_round_trips_through_plain_data() -> None:
    state = RunState.new("RUN-001", "abc123")
    state.nodes[Phase.SPEC.value].status = NodeStatus.VALID.value
    state.artifacts["spec"] = "artifacts/spec.json"

    restored = RunState.from_dict(state.to_dict())

    assert restored == state
    assert restored.to_dict()["nodes"]["spec"]["status"] == "valid"
