"""Harness-observed command evidence.

The helper never runs the repository commands: ``WorkflowRunner`` only forwards
them to children, so a ``verify`` child's claim of success is self-reported.
This module closes that gap for the orchestrator by running the configured
command itself and persisting what it observed.

Evidence lives beside the harness result files, outside ``.ai-workflow/runs``,
so it carries no run-state semantics: the helper stays the only writer of state.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
import os
from pathlib import Path

from ai_workflow.errors import AppError
from ai_workflow.workflow.runner import CommandRunner


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    """What the harness observed when it ran one phase command."""

    node: str
    child: str
    argv: tuple[str, ...]
    cwd: str
    exit_status: int
    duration_ms: int
    output_digest: str
    output_excerpt: str
    output_truncated: bool
    path: str

    @property
    def passed(self) -> bool:
        return self.exit_status == 0

    def to_dict(self) -> dict[str, object]:
        return {
            "node": self.node,
            "child": self.child,
            "argv": list(self.argv),
            "cwd": self.cwd,
            "exit_status": self.exit_status,
            "duration_ms": self.duration_ms,
            "output_digest": self.output_digest,
            "output_excerpt": self.output_excerpt,
            "output_truncated": self.output_truncated,
            "path": self.path,
        }


class EvidenceRecorder:
    """Run phase commands as harness-owned evidence."""

    def __init__(
        self,
        root: Path,
        *,
        command_runner: CommandRunner | None = None,
        excerpt_characters: int = 2000,
    ) -> None:
        self.root = root
        self.command_runner = command_runner or CommandRunner()
        self.excerpt_characters = excerpt_characters

    def record(
        self,
        *,
        run_id: str,
        attempt_id: str,
        node: str,
        child: str,
        command: tuple[str, ...],
        cwd: Path,
        timeout_seconds: int = 1800,
    ) -> EvidenceRecord:
        """Run ``command`` once and persist the observation immutably."""
        evidence = self.command_runner.run(command, cwd, timeout_seconds)
        digest = hashlib.sha256(evidence.output.encode("utf-8")).hexdigest()
        record = EvidenceRecord(
            node=node,
            child=child,
            argv=tuple(evidence.argv),
            cwd=evidence.cwd,
            exit_status=evidence.exit_status,
            duration_ms=evidence.duration_ms,
            output_digest=digest,
            output_excerpt=evidence.output[: self.excerpt_characters],
            output_truncated=evidence.output_truncated,
            path="",
        )
        path = self._path(attempt_id, child)
        payload = dict(record.to_dict())
        payload["schema_version"] = 1
        self._write_immutable(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")
        return replace(record, path=str(path))

    def _path(self, attempt_id: str, child: str) -> Path:
        # The recorder is run-scoped by construction: the orchestrator hands it the
        # run's harness directory, so the file name only needs attempt and child.
        for value, name in ((attempt_id, "attempt ID"), (child, "child")):
            if not value or any(part in value for part in ("/", "\\", "..")):
                raise AppError("invalid_storage_path", f"{name} is not a safe path component")
        return self.root / "evidence" / f"{attempt_id}-{child}.json"

    @staticmethod
    def _write_immutable(path: Path, payload: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        temporary.write_text(payload, encoding="utf-8")
        os.replace(temporary, path)
