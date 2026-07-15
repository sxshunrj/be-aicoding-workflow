from dataclasses import dataclass
import json
from pathlib import Path
from pathlib import PurePosixPath

from ai_workflow.contracts.artifacts import ArtifactRef, SCHEMA_VERSION
from ai_workflow.workflow.models import Phase


@dataclass(frozen=True, slots=True)
class KnowledgePacket:
    query: dict[str, object]
    selected_ids: tuple[str, ...]
    entries: tuple[dict[str, object], ...]
    digest: str

    def to_dict(self) -> dict[str, object]:
        return {"schema_version": SCHEMA_VERSION, "query": self.query,
                "selected_ids": list(self.selected_ids), "entries": list(self.entries),
                "digest": self.digest}


@dataclass(frozen=True, slots=True)
class PhasePacket:
    run_id: str
    phase: Phase
    attempt_id: str
    source_revision: str
    knowledge_packet: dict[str, object]
    prior_artifacts: tuple[ArtifactRef, ...]
    rerun_reason: str | None

    def to_dict(self) -> dict[str, object]:
        return {"schema_version": SCHEMA_VERSION, "run_id": self.run_id, "phase": self.phase.value,
                "attempt_id": self.attempt_id, "source_revision": self.source_revision,
                "knowledge_packet": self.knowledge_packet,
                "prior_artifacts": [item.to_dict() for item in self.prior_artifacts],
                "rerun_reason": self.rerun_reason}

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path: Path | str) -> "PhasePacket":
        path = Path(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("phase packet must be an object")
        if data.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"unsupported schema_version: {data.get('schema_version')!r}")
        expected = {"schema_version", "run_id", "phase", "attempt_id", "source_revision",
                    "knowledge_packet", "prior_artifacts", "rerun_reason"}
        if set(data) != expected:
            raise ValueError("phase packet keys are invalid")
        knowledge, artifacts = data["knowledge_packet"], data["prior_artifacts"]
        if not isinstance(knowledge, dict) or not isinstance(artifacts, list):
            raise ValueError("phase packet payload is invalid")
        for key in ("run_id", "phase", "attempt_id", "source_revision"):
            if not isinstance(data[key], str) or not data[key].strip():
                raise ValueError(f"phase packet {key} is invalid")
        if not all(isinstance(item, dict) for item in artifacts):
            raise ValueError("prior artifacts must be objects")
        reason = data["rerun_reason"]
        if reason is not None and not isinstance(reason, str):
            raise ValueError("rerun reason must be a string or null")
        return cls(data["run_id"], Phase(data["phase"]), data["attempt_id"],
                   data["source_revision"], knowledge,
                   tuple(ArtifactRef.from_dict(item) for item in artifacts), reason)


@dataclass(frozen=True, slots=True)
class DispatchPacket:
    run_id: str
    phase: Phase
    child: str
    attempt_id: str
    source_revision: str
    requirement: str
    execution_mode: str
    rerun_reason: str | None
    owner_contract_path: str
    common_contract_path: str
    allowed_input_paths: tuple[str, ...]
    allowed_output_path: str
    commands: dict[str, tuple[str, ...]]
    knowledge_packet: dict[str, str]
    prior_artifacts: tuple[ArtifactRef, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "run_id": self.run_id,
            "phase": self.phase.value,
            "child": self.child,
            "attempt_id": self.attempt_id,
            "source_revision": self.source_revision,
            "requirement": self.requirement,
            "execution_mode": self.execution_mode,
            "rerun_reason": self.rerun_reason,
            "owner_contract_path": self.owner_contract_path,
            "common_contract_path": self.common_contract_path,
            "allowed_input_paths": list(self.allowed_input_paths),
            "allowed_output_path": self.allowed_output_path,
            "commands": {name: list(argv) for name, argv in self.commands.items()},
            "knowledge_packet": self.knowledge_packet.copy(),
            "prior_artifacts": [artifact.to_dict() for artifact in self.prior_artifacts],
        }

    @classmethod
    def load(cls, path: Path | str) -> "DispatchPacket":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("dispatch packet must be an object")
        expected = {
            "schema_version",
            "run_id",
            "phase",
            "child",
            "attempt_id",
            "source_revision",
            "requirement",
            "execution_mode",
            "rerun_reason",
            "owner_contract_path",
            "common_contract_path",
            "allowed_input_paths",
            "allowed_output_path",
            "commands",
            "knowledge_packet",
            "prior_artifacts",
        }
        if set(data) != expected:
            raise ValueError("dispatch packet keys are invalid")
        if data["schema_version"] != SCHEMA_VERSION:
            raise ValueError(f"unsupported schema_version: {data['schema_version']!r}")
        for key in ("run_id", "child", "attempt_id", "source_revision", "requirement"):
            if not isinstance(data[key], str) or not data[key].strip():
                raise ValueError(f"dispatch packet {key} is invalid")
        if not isinstance(data["phase"], str):
            raise ValueError("dispatch packet phase is invalid")
        phase = Phase(data["phase"])
        mode, reason = data["execution_mode"], data["rerun_reason"]
        if (
            (mode == "fresh" and reason is not None)
            or (mode == "rerun" and (not isinstance(reason, str) or not reason.strip()))
            or mode not in ("fresh", "rerun")
        ):
            raise ValueError("dispatch packet execution mode and rerun reason are invalid")
        for key in ("owner_contract_path", "common_contract_path"):
            value = data[key]
            if not isinstance(value, str) or not Path(value).is_absolute():
                raise ValueError(f"{key} must be absolute")
        allowed_inputs = data["allowed_input_paths"]
        if not isinstance(allowed_inputs, list) or not all(
            _is_safe_repository_path(item) for item in allowed_inputs
        ):
            raise ValueError("allowed_input_paths must contain normalized repository-relative paths")
        allowed_output = data["allowed_output_path"]
        if not _is_safe_repository_path(allowed_output):
            raise ValueError("allowed_output_path must be a normalized repository-relative path")
        raw_commands = data["commands"]
        if not isinstance(raw_commands, dict) or any(
            not isinstance(name, str)
            or not name.strip()
            or not isinstance(argv, list)
            or not argv
            or not all(isinstance(argument, str) for argument in argv)
            for name, argv in raw_commands.items()
        ):
            raise ValueError("dispatch packet commands are invalid")
        knowledge = data["knowledge_packet"]
        if (
            not isinstance(knowledge, dict)
            or set(knowledge) != {"path", "sha256"}
            or not isinstance(knowledge["path"], str)
            or not Path(knowledge["path"]).is_absolute()
            or not _is_sha256(knowledge["sha256"])
        ):
            raise ValueError("dispatch packet knowledge packet is invalid")
        raw_artifacts = data["prior_artifacts"]
        if not isinstance(raw_artifacts, list) or not all(
            isinstance(artifact, dict) for artifact in raw_artifacts
        ):
            raise ValueError("prior artifacts must be a list of objects")
        return cls(
            run_id=data["run_id"],
            phase=phase,
            child=data["child"],
            attempt_id=data["attempt_id"],
            source_revision=data["source_revision"],
            requirement=data["requirement"],
            execution_mode=mode,
            rerun_reason=reason,
            owner_contract_path=data["owner_contract_path"],
            common_contract_path=data["common_contract_path"],
            allowed_input_paths=tuple(allowed_inputs),
            allowed_output_path=allowed_output,
            commands={name: tuple(argv) for name, argv in raw_commands.items()},
            knowledge_packet={"path": knowledge["path"], "sha256": knowledge["sha256"]},
            prior_artifacts=tuple(
                ArtifactRef.from_dict(artifact) for artifact in raw_artifacts
            ),
        )


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _is_safe_repository_path(value: object) -> bool:
    if not isinstance(value, str) or not value.strip() or "\\" in value:
        return False
    path = PurePosixPath(value)
    return (
        not path.is_absolute()
        and path.as_posix() == value
        and path.as_posix() != "."
        and ".." not in path.parts
    )
