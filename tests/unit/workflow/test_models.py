import pytest

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


def test_rejects_non_plain_artifact_values() -> None:
    state = RunState.new("RUN-001", "abc123")
    state.artifacts["spec"] = {"digest": ("not", "a", "list")}

    with pytest.raises(TypeError, match="plain serialization value"):
        state.to_dict()


def test_rejects_unsupported_schema_version() -> None:
    data = RunState.new("RUN-001", "abc123").to_dict()
    data["schema_version"] = 2

    with pytest.raises(ValueError, match="unsupported schema_version"):
        RunState.from_dict(data)


def test_rejects_malformed_node_entry() -> None:
    data = RunState.new("RUN-001", "abc123").to_dict()
    nodes = data["nodes"]
    assert isinstance(nodes, dict)
    nodes["spec"] = "not a mapping"

    with pytest.raises(TypeError, match="node 'spec' must be a mapping"):
        RunState.from_dict(data)
