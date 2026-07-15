from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ai_workflow.workflow.graph import RunGraphNode


def validate_plain_value(value: object, *, path: str = "value") -> None:
    if value is None or type(value) in (bool, int, float, str):
        return
    if type(value) is list:
        for index, item in enumerate(value):
            validate_plain_value(item, path=f"{path}[{index}]")
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise TypeError(f"{path} keys must be strings")
            validate_plain_value(item, path=f"{path}.{key}")
        return
    raise TypeError(
        f"{path} must be a plain serialization value; got {type(value).__name__}"
    )


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
class RunState:
    schema_version: int
    run_id: str
    version: int
    status: str
    current_phase: str
    source_revision: str
    requirement: str
    profile: str
    run_graph: dict[str, RunGraphNode]
    artifacts: dict[str, object] = field(default_factory=dict)

    @classmethod
    def new(
        cls,
        run_id: str,
        source_revision: str,
        requirement: str,
        profile: str,
        run_graph: dict[str, RunGraphNode],
    ) -> "RunState":
        from ai_workflow.workflow.graph import validate_run_graph

        cls._validate_non_blank(requirement, "requirement")
        cls._validate_non_blank(profile, "profile")
        validate_run_graph(run_graph)
        return cls(
            schema_version=2,
            run_id=run_id,
            version=0,
            status=NodeStatus.PENDING.value,
            current_phase=Phase.SPEC.value,
            source_revision=source_revision,
            requirement=requirement,
            profile=profile,
            run_graph=dict(run_graph),
            artifacts={},
        )

    def to_dict(self) -> dict[str, object]:
        data = {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "version": self.version,
            "status": self.status,
            "current_phase": self.current_phase,
            "source_revision": self.source_revision,
            "requirement": self.requirement,
            "profile": self.profile,
            "run_graph": {
                name: node.to_dict() for name, node in self.run_graph.items()
            },
            "artifacts": self.artifacts.copy(),
        }
        validate_plain_value(data)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "RunState":
        from ai_workflow.workflow.graph import RunGraphNode, validate_run_graph

        validate_plain_value(data)
        if data.get("schema_version") != 2:
            raise ValueError(
                f"unsupported schema_version: {data.get('schema_version')!r}"
            )
        raw_graph = data["run_graph"]
        raw_artifacts = data["artifacts"]
        if not isinstance(raw_graph, dict) or not isinstance(raw_artifacts, dict):
            raise TypeError("run_graph and artifacts must be mappings")
        requirement = data["requirement"]
        profile = data["profile"]
        cls._validate_non_blank(requirement, "requirement")
        cls._validate_non_blank(profile, "profile")
        run_graph: dict[str, RunGraphNode] = {}
        for name, node in raw_graph.items():
            if not isinstance(node, dict):
                raise TypeError(f"run graph node {name!r} must be a mapping")
            run_graph[name] = RunGraphNode.from_dict(name, node)
        validate_run_graph(run_graph)
        return cls(
            schema_version=int(data["schema_version"]),
            run_id=str(data["run_id"]),
            version=int(data["version"]),
            status=str(data["status"]),
            current_phase=str(data["current_phase"]),
            source_revision=str(data["source_revision"]),
            requirement=requirement,
            profile=profile,
            run_graph=run_graph,
            artifacts={str(name): value for name, value in raw_artifacts.items()},
        )

    @staticmethod
    def _validate_non_blank(value: object, name: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must not be blank")
