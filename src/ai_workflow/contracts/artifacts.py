from dataclasses import dataclass
import json
from pathlib import Path
from typing import Literal

from ai_workflow.workflow.models import Phase


SCHEMA_VERSION = 2


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
    child: str
    source_revision: str

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "schema_version": self.schema_version,
            "phase": self.phase.value,
            "child": self.child,
            "source_revision": self.source_revision,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "ArtifactRef":
        _keys(
            data,
            {"path", "sha256", "schema_version", "phase", "child", "source_revision"},
            "artifact",
        )
        if data["schema_version"] != SCHEMA_VERSION:
            raise ValueError(f"unsupported schema_version: {data['schema_version']!r}")
        if not isinstance(data["path"], str) or not data["path"].strip():
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
        if not isinstance(data["child"], str) or not data["child"].strip():
            raise ValueError("artifact child is invalid")
        return cls(
            path=data["path"],
            sha256=digest,
            schema_version=SCHEMA_VERSION,
            phase=Phase(data["phase"]),
            child=data["child"],
            source_revision=data["source_revision"],
        )


@dataclass(frozen=True, slots=True)
class ChildResult:
    run_id: str
    phase: Phase
    child: str
    attempt_id: str
    execution_mode: Literal["fresh", "rerun"]
    status: Literal["completed", "unable_to_complete"]
    summary: str
    artifact: ArtifactRef | None
    findings: tuple[Finding, ...]
    knowledge_citations: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "run_id": self.run_id,
            "phase": self.phase.value,
            "child": self.child,
            "attempt_id": self.attempt_id,
            "execution_mode": self.execution_mode,
            "status": self.status,
            "summary": self.summary,
            "artifact": None if self.artifact is None else self.artifact.to_dict(),
            "findings": [finding.to_dict() for finding in self.findings],
            "knowledge_citations": list(self.knowledge_citations),
        }

    def write(self, path: Path) -> None:
        path.write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "ChildResult":
        return cls.from_bytes(path.read_bytes())

    @classmethod
    def from_json(cls, path: Path) -> "ChildResult":
        return cls.load(path)

    @classmethod
    def from_bytes(cls, payload: bytes) -> "ChildResult":
        data = json.loads(payload.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("child result must be an object")
        if "schema_version" not in data:
            raise ValueError("schema_version is required")
        if data["schema_version"] != SCHEMA_VERSION:
            raise ValueError(f"unsupported schema_version: {data['schema_version']!r}")
        _keys(
            data,
            {
                "schema_version",
                "run_id",
                "phase",
                "child",
                "attempt_id",
                "execution_mode",
                "status",
                "summary",
                "artifact",
                "findings",
                "knowledge_citations",
            },
            "child result",
        )
        for key in ("run_id", "child", "attempt_id"):
            if not isinstance(data[key], str) or not data[key].strip():
                raise ValueError(f"child result {key} is invalid")
        if not isinstance(data["phase"], str):
            raise ValueError("child result phase is invalid")
        phase = Phase(data["phase"])
        execution_mode = data["execution_mode"]
        if execution_mode not in ("fresh", "rerun"):
            raise ValueError("child result execution mode is invalid")
        status = data["status"]
        if status not in ("completed", "unable_to_complete"):
            raise ValueError("child result status is invalid")
        if not isinstance(data["summary"], str) or not data["summary"].strip():
            raise ValueError("child result summary must not be empty")
        artifact_data = data["artifact"]
        if artifact_data is not None and not isinstance(artifact_data, dict):
            raise ValueError("artifact must be an object or null")
        if status == "completed" and artifact_data is None:
            raise ValueError("completed child result requires an artifact")
        findings_data = data["findings"]
        if not isinstance(findings_data, list) or not all(isinstance(item, dict) for item in findings_data):
            raise ValueError("findings must be a list")
        citations = data["knowledge_citations"]
        if (not isinstance(citations, list) or not all(isinstance(item, str) and item.strip()
                                                       for item in citations)
                or len(citations) != len(set(citations))):
            raise ValueError("knowledge_citations must be a unique non-empty string list")
        artifact = None if artifact_data is None else ArtifactRef.from_dict(artifact_data)
        if artifact is not None and (artifact.phase is not phase or artifact.child != data["child"]):
            raise ValueError("artifact owner does not match child result")
        return cls(
            run_id=data["run_id"],
            phase=phase,
            child=data["child"],
            attempt_id=data["attempt_id"],
            execution_mode=execution_mode,
            status=status,
            summary=data["summary"],
            artifact=artifact,
            findings=tuple(Finding.from_dict(item) for item in findings_data),
            knowledge_citations=tuple(citations),
        )
