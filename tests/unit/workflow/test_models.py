import pytest

from ai_workflow.errors import AppError
from ai_workflow.workflow.graph import NodeValidity, RunGraphNode, WorkflowProfile
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


def grill_graph() -> dict[str, RunGraphNode]:
    return {
        "plan.prd": RunGraphNode("plan.prd", Phase.PLAN, "prd"),
        "implement.code": RunGraphNode("implement.code", Phase.IMPLEMENT, "code"),
        "verify.code_review": RunGraphNode(
            "verify.code_review", Phase.VERIFY, "code_review"
        ),
    }


def test_new_run_stores_schema_v2_profile_and_run_graph() -> None:
    graph = sample_graph()

    state = RunState.new(
        "RUN-001",
        "abc123",
        "Add the workflow graph",
        WorkflowProfile.FULL,
        graph,
        Phase.SPEC,
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


def test_new_grill_run_uses_persisted_initial_phase() -> None:
    state = RunState.new(
        "RUN-001",
        "abc123",
        "Write PRD first",
        WorkflowProfile.GRILL,
        grill_graph(),
        Phase.PLAN,
    )

    assert state.profile == "grill"
    assert state.current_phase == "plan"
    assert tuple(state.run_graph) == ("plan.prd", "implement.code", "verify.code_review")


def test_run_state_round_trips_through_plain_data() -> None:
    state = RunState.new(
        "RUN-001",
        "abc123",
        "Add the workflow graph",
        WorkflowProfile.FULL,
        sample_graph(),
        Phase.SPEC,
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
        "RUN-001",
        "abc123",
        "Add the workflow graph",
        WorkflowProfile.FULL,
        sample_graph(),
        Phase.SPEC,
    )
    state.artifacts["spec"] = {"digest": ("not", "a", "list")}

    with pytest.raises(TypeError, match="plain serialization value"):
        state.to_dict()


def test_serialization_rejects_mechanically_invalid_run_graph() -> None:
    state = RunState.new(
        "RUN-001",
        "abc123",
        "Add the workflow graph",
        WorkflowProfile.FULL,
        sample_graph(),
        Phase.SPEC,
    )
    state.run_graph["implement.code"].validity = NodeValidity.RERUN

    with pytest.raises(AppError, match="rerun node requires a reason") as error:
        state.to_dict()

    assert error.value.code == "invalid_run_graph"


@pytest.mark.parametrize(("requirement", "profile"), [("  ", "full"), ("work", "")])
def test_new_run_rejects_blank_requirement_or_profile(
    requirement: str, profile: str
) -> None:
    with pytest.raises((AppError, ValueError), match="must not be blank|not a valid"):
        RunState.new(
            "RUN-001", "abc123", requirement, profile, sample_graph(), Phase.SPEC
        )


def test_rejects_unsupported_schema_version() -> None:
    data = RunState.new(
        "RUN-001",
        "abc123",
        "Add the workflow graph",
        WorkflowProfile.FULL,
        sample_graph(),
        Phase.SPEC,
    ).to_dict()
    data["schema_version"] = 1

    with pytest.raises(AppError, match="unsupported schema_version") as error:
        RunState.from_dict(data)

    assert error.value.code == "unsupported_schema_version"


def test_rejects_blank_persisted_requirement() -> None:
    data = RunState.new(
        "RUN-001",
        "abc123",
        "Add the workflow graph",
        WorkflowProfile.FULL,
        sample_graph(),
        Phase.SPEC,
    ).to_dict()
    data["requirement"] = " "

    with pytest.raises(ValueError, match="requirement must not be blank"):
        RunState.from_dict(data)


def test_rejects_malformed_run_graph_entry() -> None:
    data = RunState.new(
        "RUN-001",
        "abc123",
        "Add the workflow graph",
        WorkflowProfile.FULL,
        sample_graph(),
        Phase.SPEC,
    ).to_dict()
    run_graph = data["run_graph"]
    assert isinstance(run_graph, dict)
    run_graph["spec.spec"] = "not a mapping"

    with pytest.raises(
        TypeError, match="run graph node 'spec.spec' must be a mapping"
    ):
        RunState.from_dict(data)


def test_rejects_persisted_profile_graph_mismatch() -> None:
    data = RunState.new(
        "RUN-001",
        "abc123",
        "Write PRD first",
        WorkflowProfile.GRILL,
        grill_graph(),
        Phase.PLAN,
    ).to_dict()
    data["profile"] = "full"

    with pytest.raises(AppError) as error:
        RunState.from_dict(data)

    assert error.value.code == "invalid_run_graph"


def test_rejects_initial_phase_absent_from_graph() -> None:
    with pytest.raises(AppError) as error:
        RunState.new(
            "RUN-001",
            "abc123",
            "Write PRD first",
            WorkflowProfile.GRILL,
            grill_graph(),
            Phase.SPEC,
        )

    assert error.value.code == "invalid_run_graph"
