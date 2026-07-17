from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from ai_workflow.config import RepositoryConfig
from ai_workflow.errors import AppError
from ai_workflow.workflow.models import Phase


class NodeValidity(StrEnum):
    PENDING = "pending"
    VALID = "valid"
    RERUN = "rerun"


class WorkflowProfile(StrEnum):
    FULL = "full"
    GRILL = "grill"


@dataclass(slots=True)
class RunGraphNode:
    key: str
    phase: Phase
    child: str
    validity: NodeValidity = NodeValidity.PENDING
    reason: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "phase": self.phase.value,
            "child": self.child,
            "validity": self.validity.value,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, key: str, data: dict[str, object]) -> "RunGraphNode":
        if set(data) != {"phase", "child", "validity", "reason"}:
            raise AppError("invalid_run_graph", "run graph node has invalid keys")
        child = data["child"]
        reason = data["reason"]
        if not isinstance(child, str) or not child:
            raise AppError(
                "invalid_run_graph", "run graph child must be a non-empty string"
            )
        if reason is not None and not isinstance(reason, str):
            raise AppError(
                "invalid_run_graph", "run graph reason must be a string or null"
            )
        return cls(
            key=key,
            phase=Phase(data["phase"]),
            child=child,
            validity=NodeValidity(data["validity"]),
            reason=reason,
        )


@dataclass(frozen=True, slots=True)
class RunGraphDefinition:
    nodes: dict[str, RunGraphNode]
    initial_phase: Phase


_FULL_RUN_GRAPH = (
    ("spec.spec", Phase.SPEC, "spec", None),
    ("plan.solution", Phase.PLAN, "solution", None),
    ("plan.test_strategy", Phase.PLAN, "test_strategy", None),
    ("implement.code", Phase.IMPLEMENT, "code", None),
    ("verify.build", Phase.VERIFY, "build", "build"),
    ("verify.unit_test", Phase.VERIFY, "unit_test", "unit_test"),
    (
        "verify.integration_test",
        Phase.VERIFY,
        "integration_test",
        "integration_test",
    ),
    ("verify.code_review", Phase.VERIFY, "code_review", None),
)
_FULL_MANDATORY_NODES = {
    "spec.spec",
    "plan.solution",
    "implement.code",
    "verify.code_review",
}
_GRILL_RUN_GRAPH = (
    ("plan.prd", Phase.PLAN, "prd", None),
    ("implement.code", Phase.IMPLEMENT, "code", None),
    ("verify.build", Phase.VERIFY, "build", "build"),
    ("verify.unit_test", Phase.VERIFY, "unit_test", "unit_test"),
    (
        "verify.integration_test",
        Phase.VERIFY,
        "integration_test",
        "integration_test",
    ),
    ("verify.code_review", Phase.VERIFY, "code_review", None),
)
_GRILL_MANDATORY_NODES = {
    "plan.prd",
    "implement.code",
    "verify.code_review",
}
_PROFILE_DEFINITIONS = {
    WorkflowProfile.FULL: (
        _FULL_RUN_GRAPH,
        Phase.SPEC,
        _FULL_MANDATORY_NODES,
    ),
    WorkflowProfile.GRILL: (
        _GRILL_RUN_GRAPH,
        Phase.PLAN,
        _GRILL_MANDATORY_NODES,
    ),
}


def build_run_graph(
    config: RepositoryConfig,
    profile: WorkflowProfile = WorkflowProfile.FULL,
) -> RunGraphDefinition:
    template, initial_phase, mandatory = _PROFILE_DEFINITIONS[profile]
    disabled = set(config.disabled_nodes)
    disabled_mandatory = disabled & mandatory
    if disabled_mandatory:
        key = min(disabled_mandatory)
        raise AppError(
            "config_invalid",
            f"mandatory run graph node cannot be disabled: {key}",
        )
    graph: dict[str, RunGraphNode] = {}
    for key, phase, child, command_name in template:
        if key in disabled:
            continue
        if command_name is not None and config.command(command_name) is None:
            continue
        graph[key] = RunGraphNode(key=key, phase=phase, child=child)
    validate_run_graph(graph, profile)
    return RunGraphDefinition(nodes=graph, initial_phase=initial_phase)


def validate_run_graph(
    graph: dict[str, RunGraphNode],
    profile: WorkflowProfile = WorkflowProfile.FULL,
) -> None:
    for key, node in graph.items():
        if key != node.key:
            raise AppError(
                "invalid_run_graph", "run graph node key does not match mapping key"
            )
        expected_prefix = f"{node.phase.value}."
        if not key.startswith(expected_prefix):
            raise AppError(
                "invalid_run_graph", "run graph node phase does not match its key"
            )
        if not node.child:
            raise AppError(
                "invalid_run_graph", "run graph child must be a non-empty string"
            )
        if node.validity is NodeValidity.RERUN:
            if node.reason is None or not node.reason.strip():
                raise AppError("invalid_run_graph", "rerun node requires a reason")
        elif node.reason is not None:
            raise AppError(
                "invalid_run_graph", "non-rerun node must not have a reason"
            )

    _, _, mandatory = _PROFILE_DEFINITIONS[profile]
    missing = mandatory - set(graph)
    if missing:
        key = min(missing)
        raise AppError("invalid_run_graph", f"mandatory run graph node is missing: {key}")


def execution_kind(
    node: RunGraphNode,
) -> Literal["child_backed", "workflow_owned"]:
    return "workflow_owned" if node.key == "plan.prd" else "child_backed"
