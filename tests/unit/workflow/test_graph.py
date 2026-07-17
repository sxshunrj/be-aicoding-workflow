from pathlib import Path

import pytest

from ai_workflow.config import RepositoryConfig
from ai_workflow.errors import AppError
from ai_workflow.workflow.graph import (
    NodeValidity,
    RunGraphNode,
    WorkflowProfile,
    build_run_graph,
    execution_kind,
    validate_run_graph,
)
from ai_workflow.workflow.models import Phase


def test_builds_language_neutral_run_graph_from_commands(tmp_path: Path) -> None:
    (tmp_path / ".ai-workflow.yaml").write_text(
        "repository: demo\n"
        "commands:\n"
        "  build: [bash, verify.sh, build]\n"
        "  unit_test: [bash, verify.sh, test]\n"
        "disabled_nodes: [verify.integration_test]\n",
        encoding="utf-8",
    )

    definition = build_run_graph(RepositoryConfig.load(tmp_path), WorkflowProfile.FULL)
    graph = definition.nodes

    assert definition.initial_phase is Phase.SPEC
    assert tuple(graph) == (
        "spec.spec",
        "plan.solution",
        "plan.test_strategy",
        "implement.code",
        "verify.build",
        "verify.unit_test",
        "verify.code_review",
    )
    assert all(node.validity is NodeValidity.PENDING for node in graph.values())


def test_command_gated_and_explicitly_disabled_nodes_are_omitted(tmp_path: Path) -> None:
    (tmp_path / ".ai-workflow.yaml").write_text(
        "repository: demo\n"
        "commands:\n"
        "  build: [make]\n"
        "  integration_test: [pytest, integration]\n"
        "disabled_nodes: [plan.test_strategy, verify.build]\n",
        encoding="utf-8",
    )

    graph = build_run_graph(
        RepositoryConfig.load(tmp_path), WorkflowProfile.FULL
    ).nodes

    assert tuple(graph) == (
        "spec.spec",
        "plan.solution",
        "implement.code",
        "verify.integration_test",
        "verify.code_review",
    )


@pytest.mark.parametrize(
    "mandatory_node",
    ["spec.spec", "plan.solution", "implement.code", "verify.code_review"],
)
def test_rejects_disabled_mandatory_node(
    tmp_path: Path, mandatory_node: str
) -> None:
    (tmp_path / ".ai-workflow.yaml").write_text(
        f"repository: demo\ndisabled_nodes: [{mandatory_node}]\n",
        encoding="utf-8",
    )

    with pytest.raises(AppError, match="mandatory run graph node cannot be disabled"):
        build_run_graph(RepositoryConfig.load(tmp_path), WorkflowProfile.FULL)


def test_builds_grill_profile_graph_with_prd_initial_phase(tmp_path: Path) -> None:
    (tmp_path / ".ai-workflow.yaml").write_text(
        "repository: demo\n"
        "commands:\n"
        "  build: [bash, verify.sh, build]\n"
        "  unit_test: [bash, verify.sh, test]\n"
        "  integration_test: [bash, verify.sh, integration]\n",
        encoding="utf-8",
    )

    definition = build_run_graph(RepositoryConfig.load(tmp_path), WorkflowProfile.GRILL)

    assert definition.initial_phase is Phase.PLAN
    assert tuple(definition.nodes) == (
        "plan.prd",
        "implement.code",
        "verify.build",
        "verify.unit_test",
        "verify.integration_test",
        "verify.code_review",
    )
    assert "spec.spec" not in definition.nodes
    assert execution_kind(definition.nodes["plan.prd"]) == "workflow_owned"
    assert execution_kind(definition.nodes["implement.code"]) == "child_backed"


def test_grill_omits_command_gated_verify_nodes(tmp_path: Path) -> None:
    (tmp_path / ".ai-workflow.yaml").write_text("repository: demo\n", encoding="utf-8")

    definition = build_run_graph(RepositoryConfig.load(tmp_path), WorkflowProfile.GRILL)

    assert tuple(definition.nodes) == (
        "plan.prd",
        "implement.code",
        "verify.code_review",
    )


def test_grill_rejects_disabled_mandatory_node(tmp_path: Path) -> None:
    (tmp_path / ".ai-workflow.yaml").write_text(
        "repository: demo\ndisabled_nodes: [plan.prd]\n",
        encoding="utf-8",
    )

    with pytest.raises(AppError, match="mandatory run graph node cannot be disabled"):
        build_run_graph(RepositoryConfig.load(tmp_path), WorkflowProfile.GRILL)


def test_run_graph_node_round_trips_plain_data() -> None:
    node = RunGraphNode(
        key="implement.code",
        phase=Phase.IMPLEMENT,
        child="code",
        validity=NodeValidity.RERUN,
        reason="tests exposed a missing branch",
    )

    restored = RunGraphNode.from_dict(node.key, node.to_dict())

    assert restored == node


def test_rerun_node_requires_non_empty_reason() -> None:
    graph = {
        "implement.code": RunGraphNode(
            key="implement.code",
            phase=Phase.IMPLEMENT,
            child="code",
            validity=NodeValidity.RERUN,
            reason=None,
        )
    }

    with pytest.raises(AppError, match="rerun node requires a reason"):
        validate_run_graph(graph, WorkflowProfile.FULL)


def test_rejects_mismatched_run_graph_key() -> None:
    graph = {
        "plan.solution": RunGraphNode(
            key="plan.test_strategy",
            phase=Phase.PLAN,
            child="test_strategy",
        )
    }

    with pytest.raises(AppError, match="run graph node key does not match"):
        validate_run_graph(graph, WorkflowProfile.FULL)


def test_validate_rejects_cross_profile_graph() -> None:
    graph = {
        "plan.prd": RunGraphNode("plan.prd", Phase.PLAN, "prd"),
        "implement.code": RunGraphNode("implement.code", Phase.IMPLEMENT, "code"),
        "verify.code_review": RunGraphNode(
            "verify.code_review", Phase.VERIFY, "code_review"
        ),
    }

    with pytest.raises(AppError, match="mandatory run graph node is missing"):
        validate_run_graph(graph, WorkflowProfile.FULL)


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (
            {"phase": "spec", "child": "spec", "validity": "pending"},
            "run graph node has invalid keys",
        ),
        (
            {"phase": "spec", "child": "", "validity": "pending", "reason": None},
            "run graph child must be a non-empty string",
        ),
        (
            {"phase": "spec", "child": "spec", "validity": "pending", "reason": []},
            "run graph reason must be a string or null",
        ),
    ],
)
def test_rejects_malformed_run_graph_node(
    data: dict[str, object], message: str
) -> None:
    with pytest.raises(AppError, match=message):
        RunGraphNode.from_dict("spec.spec", data)
