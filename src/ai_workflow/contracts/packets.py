from dataclasses import dataclass
import json
from pathlib import Path

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
