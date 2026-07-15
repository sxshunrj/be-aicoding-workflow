import pytest

from ai_workflow.workflow.graph import NodeValidity, RunGraphNode
from ai_workflow.workflow.models import NodeStatus, Phase, RunState


def sample_graph() -> dict[str, RunGraphNode]:
    return {
        "spec.spec": RunGraphNode("spec.spec", Phase.SPEC, "spec"),
        "plan.solution": RunGraphNode("plan.solution", Phase.PLAN, "solution"),
        "implement.code": RunGraphNode("implement.code", Phase.IMPLEMENT, "code"),
        "verify.code_review": RunGraphNode(
            "verify.code_review", Phase.VERIFY, "code_review"
        ),
    }


def test_new_run_stores_schema_v2_profile_and_run_graph() -> None:
    graph = sample_graph()

    state = RunState.new(
        "RUN-001", "abc123", "Add the workflow graph", "full", graph
    )

    assert state.schema_version == 2
    assert state.version == 0
    assert state.status == NodeStatus.PENDING.value
    assert state.current_phase == Phase.SPEC.value
    assert state.requirement == "Add the workflow graph"
    assert state.profile == "full"
    assert state.run_graph == graph
    assert not hasattr(state, "nodes")
    assert state.artifacts == {}


def test_run_state_round_trips_through_plain_data() -> None:
    state = RunState.new(
        "RUN-001", "abc123", "Add the workflow graph", "full", sample_graph()
    )
    state.run_graph["spec.spec"].validity = NodeValidity.VALID
    state.artifacts["spec"] = "artifacts/spec.json"

    restored = RunState.from_dict(state.to_dict())

    assert restored == state
    run_graph = restored.to_dict()["run_graph"]
    assert isinstance(run_graph, dict)
    assert run_graph["spec.spec"]["validity"] == "valid"


def test_rejects_non_plain_artifact_values() -> None:
    state = RunState.new(
        "RUN-001", "abc123", "Add the workflow graph", "full", sample_graph()
    )
    state.artifacts["spec"] = {"digest": ("not", "a", "list")}

    with pytest.raises(TypeError, match="plain serialization value"):
        state.to_dict()


@pytest.mark.parametrize(("requirement", "profile"), [("  ", "full"), ("work", "")])
def test_new_run_rejects_blank_requirement_or_profile(
    requirement: str, profile: str
) -> None:
    with pytest.raises(ValueError, match="must not be blank"):
        RunState.new("RUN-001", "abc123", requirement, profile, sample_graph())


def test_rejects_unsupported_schema_version() -> None:
    data = RunState.new(
        "RUN-001", "abc123", "Add the workflow graph", "full", sample_graph()
    ).to_dict()
    data["schema_version"] = 1

    with pytest.raises(ValueError, match="unsupported schema_version"):
        RunState.from_dict(data)


def test_rejects_blank_persisted_requirement() -> None:
    data = RunState.new(
        "RUN-001", "abc123", "Add the workflow graph", "full", sample_graph()
    ).to_dict()
    data["requirement"] = " "

    with pytest.raises(ValueError, match="requirement must not be blank"):
        RunState.from_dict(data)


def test_rejects_malformed_run_graph_entry() -> None:
    data = RunState.new(
        "RUN-001", "abc123", "Add the workflow graph", "full", sample_graph()
    ).to_dict()
    run_graph = data["run_graph"]
    assert isinstance(run_graph, dict)
    run_graph["spec.spec"] = "not a mapping"

    with pytest.raises(
        TypeError, match="run graph node 'spec.spec' must be a mapping"
    ):
        RunState.from_dict(data)
