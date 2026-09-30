"""Harness-observed command evidence.

The helper never runs the repository commands: it only forwards them to children,
so a ``verify`` child's claim of success is self-reported. This module closes that
gap for the orchestrator by running the configured command itself and reporting
what it observed.

Persisting the observation is the service's job
(:meth:`WorkflowService.record_evidence`), which keeps every run-state write in
one place: this module only observes.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path

from ai_workflow.workflow.runner import CommandRunner


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    """One command the harness ran and what it saw."""

    node: str
    child: str
    argv: tuple[str, ...]
    cwd: str
    exit_status: int
    duration_ms: int
    output_digest: str
    output_excerpt: str
    output_truncated: bool
    path: str = ""

    @property
    def passed(self) -> bool:
        return self.exit_status == 0

    def to_payload(self) -> dict[str, object]:
        """Lossless observation payload; the registered path is added on persist."""
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
        }


class EvidenceRecorder:
    """Run phase commands as harness-owned observations."""

    def __init__(
        self,
        *,
        command_runner: CommandRunner | None = None,
        excerpt_characters: int = 2000,
    ) -> None:
        self.command_runner = command_runner or CommandRunner()
        self.excerpt_characters = excerpt_characters

    def record(
        self,
        *,
        node: str,
        child: str,
        command: tuple[str, ...],
        cwd: Path,
        timeout_seconds: int = 1800,
    ) -> EvidenceRecord:
        """Run ``command`` once and return what the harness observed."""
        evidence = self.command_runner.run(command, cwd, timeout_seconds)
        return EvidenceRecord(
            node=node,
            child=child,
            argv=tuple(evidence.argv),
            cwd=evidence.cwd,
            exit_status=evidence.exit_status,
            duration_ms=evidence.duration_ms,
            output_digest=hashlib.sha256(evidence.output.encode("utf-8")).hexdigest(),
            output_excerpt=evidence.output[: self.excerpt_characters],
            output_truncated=evidence.output_truncated,
        )
