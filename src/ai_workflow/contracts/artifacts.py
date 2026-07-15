from dataclasses import dataclass
import json
from pathlib import Path
from typing import Literal

from ai_workflow.workflow.models import Phase


SCHEMA_VERSION = 1


def _keys(data: dict[str, object], expected: set[str], name: str) -> None:
    missing, unknown = expected - set(data), set(data) - expected
    if missing or unknown:
        raise ValueError(f"invalid {name} keys; missing={sorted(missing)}, unknown={sorted(unknown)}")


@dataclass(frozen=True, slots=True)
class Finding:
    id: str
    title: str
    detail: str

    def to_dict(self) -> dict[str, object]:
        return {"id": self.id, "title": self.title, "detail": self.detail}

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "Finding":
        _keys(data, {"id", "title", "detail"}, "finding")
        if not all(isinstance(data[key], str) for key in ("id", "title", "detail")):
            raise ValueError("finding fields must be strings")
        return cls(data["id"], data["title"], data["detail"])


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    path: str
    sha256: str
    schema_version: int
    phase: Phase
    source_revision: str

    def to_dict(self) -> dict[str, object]:
        return {"path": self.path, "sha256": self.sha256, "schema_version": self.schema_version,
                "phase": self.phase.value, "source_revision": self.source_revision}

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "ArtifactRef":
        _keys(data, {"path", "sha256", "schema_version", "phase", "source_revision"}, "artifact")
        if data["schema_version"] != SCHEMA_VERSION:
            raise ValueError(f"unsupported schema_version: {data['schema_version']!r}")
        if not isinstance(data["path"], str) or not data["path"]:
            raise ValueError("artifact path is invalid")
        if not isinstance(data["source_revision"], str) or not data["source_revision"].strip():
            raise ValueError("artifact source revision is invalid")
        if not isinstance(data["sha256"], str):
            raise ValueError("artifact sha256 is invalid")
        digest = data["sha256"]
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("artifact sha256 is invalid")
        if not isinstance(data["phase"], str):
            raise ValueError("artifact phase is invalid")
        return cls(data["path"], digest, SCHEMA_VERSION, Phase(data["phase"]), data["source_revision"])


@dataclass(frozen=True, slots=True)
class ChildResult:
    status: Literal["completed", "unable_to_complete"]
    summary: str
    artifact: ArtifactRef | None
    findings: tuple[Finding, ...]
    knowledge_citations: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {"schema_version": SCHEMA_VERSION, "status": self.status, "summary": self.summary,
                "artifact": None if self.artifact is None else self.artifact.to_dict(),
                "findings": [finding.to_dict() for finding in self.findings],
                "knowledge_citations": list(self.knowledge_citations)}

    def write(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "ChildResult":
        return cls.from_bytes(path.read_bytes())

    @classmethod
    def from_bytes(cls, payload: bytes) -> "ChildResult":
        data = json.loads(payload.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("child result must be an object")
        if "schema_version" not in data:
            raise ValueError("schema_version is required")
        if data["schema_version"] != SCHEMA_VERSION:
            raise ValueError(f"unsupported schema_version: {data['schema_version']!r}")
        _keys(data, {"schema_version", "status", "summary", "artifact", "findings",
                     "knowledge_citations"}, "child result")
        status = data["status"]
        if status not in ("completed", "unable_to_complete"):
            raise ValueError("child result status is invalid")
        if not isinstance(data["summary"], str) or not data["summary"].strip():
            raise ValueError("child result summary must not be empty")
        artifact_data = data["artifact"]
        if artifact_data is not None and not isinstance(artifact_data, dict):
            raise ValueError("artifact must be an object or null")
        findings_data = data["findings"]
        if not isinstance(findings_data, list) or not all(isinstance(item, dict) for item in findings_data):
            raise ValueError("findings must be a list")
        citations = data["knowledge_citations"]
        if (not isinstance(citations, list) or not all(isinstance(item, str) and item
                                                       for item in citations)
                or len(citations) != len(set(citations))):
            raise ValueError("knowledge_citations must be a unique string list")
        return cls(status, data["summary"], None if artifact_data is None else ArtifactRef.from_dict(artifact_data),
                   tuple(Finding.from_dict(item) for item in findings_data), tuple(citations))
