from dataclasses import dataclass, field
from enum import StrEnum


class Phase(StrEnum):
    SPEC = "spec"
    PLAN = "plan"
    IMPLEMENT = "implement"
    VERIFY = "verify"


class NodeStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    VALID = "valid"
    RERUN = "rerun"
    BLOCKED = "blocked"


@dataclass(slots=True)
class WorkflowNode:
    phase: str
    status: str = NodeStatus.PENDING.value

    def to_dict(self) -> dict[str, object]:
        return {"phase": self.phase, "status": self.status}

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "WorkflowNode":
        return cls(phase=str(data["phase"]), status=str(data["status"]))


@dataclass(slots=True)
class RunState:
    schema_version: int
    run_id: str
    version: int
    status: str
    current_phase: str
    source_revision: str
    nodes: dict[str, WorkflowNode] = field(default_factory=dict)
    artifacts: dict[str, object] = field(default_factory=dict)

    @classmethod
    def new(cls, run_id: str, source_revision: str) -> "RunState":
        nodes = {
            phase.value: WorkflowNode(phase=phase.value)
            for phase in Phase
        }
        return cls(
            schema_version=1,
            run_id=run_id,
            version=0,
            status=NodeStatus.PENDING.value,
            current_phase=Phase.SPEC.value,
            source_revision=source_revision,
            nodes=nodes,
            artifacts={},
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "version": self.version,
            "status": self.status,
            "current_phase": self.current_phase,
            "source_revision": self.source_revision,
            "nodes": {name: node.to_dict() for name, node in self.nodes.items()},
            "artifacts": self.artifacts.copy(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "RunState":
        raw_nodes = data["nodes"]
        raw_artifacts = data["artifacts"]
        if not isinstance(raw_nodes, dict) or not isinstance(raw_artifacts, dict):
            raise TypeError("nodes and artifacts must be mappings")
        return cls(
            schema_version=int(data["schema_version"]),
            run_id=str(data["run_id"]),
            version=int(data["version"]),
            status=str(data["status"]),
            current_phase=str(data["current_phase"]),
            source_revision=str(data["source_revision"]),
            nodes={
                str(name): WorkflowNode.from_dict(node)
                for name, node in raw_nodes.items()
                if isinstance(node, dict)
            },
            artifacts={str(name): value for name, value in raw_artifacts.items()},
        )
