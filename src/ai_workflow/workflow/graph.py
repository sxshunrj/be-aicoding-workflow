from dataclasses import dataclass
from enum import StrEnum

from ai_workflow.config import RepositoryConfig
from ai_workflow.errors import AppError
from ai_workflow.workflow.models import Phase


class NodeValidity(StrEnum):
    PENDING = "pending"
    VALID = "valid"
    RERUN = "rerun"


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


_DEFAULT_RUN_GRAPH = (
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
_MANDATORY_NODES = {
    "spec.spec",
    "plan.solution",
    "implement.code",
    "verify.code_review",
}


def build_run_graph(config: RepositoryConfig) -> dict[str, RunGraphNode]:
    disabled = set(config.disabled_nodes)
    disabled_mandatory = disabled & _MANDATORY_NODES
    if disabled_mandatory:
        key = min(disabled_mandatory)
        raise AppError(
            "config_invalid",
            f"mandatory run graph node cannot be disabled: {key}",
        )
    graph: dict[str, RunGraphNode] = {}
    for key, phase, child, command_name in _DEFAULT_RUN_GRAPH:
        if key in disabled:
            continue
        if command_name is not None and config.command(command_name) is None:
            continue
        graph[key] = RunGraphNode(key=key, phase=phase, child=child)
    validate_run_graph(graph)
    return graph


def validate_run_graph(graph: dict[str, RunGraphNode]) -> None:
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

    missing = _MANDATORY_NODES - set(graph)
    if missing:
        key = min(missing)
        raise AppError("invalid_run_graph", f"mandatory run graph node is missing: {key}")
