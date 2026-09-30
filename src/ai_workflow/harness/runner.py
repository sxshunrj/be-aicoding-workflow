"""Child dispatch adapters for the orchestrator.

A child is whatever produces one schema-v2 ``ChildResult`` for one dispatch
item. The loop never inspects or repairs that payload: it takes the bytes a
runner returns and hands them to ``workflow stage``, so the helper stays the
only writer of run state.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
from typing import Protocol

from ai_workflow.errors import AppError


@dataclass(frozen=True, slots=True)
class ChildRequest:
    """One child the orchestrator must run for the current attempt."""

    node: str
    child: str
    action: str
    prompt_file: str | None
    packet_file: str | None


@dataclass(frozen=True, slots=True)
class ChildOutcome:
    """The raw result of running one child, or the transport failure that replaced it."""

    node: str
    child: str
    result_bytes: bytes | None = None
    failure: str | None = None

    @property
    def ok(self) -> bool:
        return self.result_bytes is not None

    @classmethod
    def failed(cls, request: ChildRequest, reason: str) -> "ChildOutcome":
        return cls(request.node, request.child, None, reason)


class ChildRunner(Protocol):
    """Runs one child and returns its raw ``ChildResult`` JSON bytes."""

    def run(self, request: ChildRequest, result_path: Path) -> ChildOutcome:
        """Run ``request``, asking the child to write ``result_path``."""
        ...


class SubprocessChildRunner:
    """Run each child as a subprocess described by an argv template.

    The template substitutes ``{prompt_file}``, ``{packet_file}``, ``{node}``,
    ``{child}``, ``{repo}`` and ``{result_file}``. Two result paths are
    supported, because clients differ:

    * the template contains ``{result_file}`` and the child writes the
      ``ChildResult`` JSON there;
    * otherwise the child prints the JSON on stdout.

    Either way the runner returns bytes and never interprets them.
    """

    def __init__(
        self,
        argv_template: tuple[str, ...],
        *,
        repo_root: Path,
        timeout_seconds: int = 1800,
        output_limit: int = 4000,
    ) -> None:
        if not argv_template:
            raise AppError("invalid_child_template", "child argv template must not be empty")
        self.argv_template = argv_template
        self.repo_root = repo_root
        self.timeout_seconds = timeout_seconds
        self.output_limit = output_limit

    @property
    def wants_result_file(self) -> bool:
        return any("{result_file}" in token for token in self.argv_template)

    def argv(self, request: ChildRequest, result_path: Path) -> tuple[str, ...]:
        substitutions = {
            "prompt_file": request.prompt_file or "",
            "packet_file": request.packet_file or "",
            "node": request.node,
            "child": request.child,
            "repo": str(self.repo_root),
            "result_file": str(result_path),
        }
        # Plain replacement, not str.format: a template token may legitimately
        # contain braces (shell snippets, JSON, python -c bodies).
        return tuple(_substitute(token, substitutions) for token in self.argv_template)

    def run(self, request: ChildRequest, result_path: Path) -> ChildOutcome:
        argv = self.argv(request, result_path)
        result_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            completed = subprocess.run(
                list(argv),
                shell=False,
                cwd=self.repo_root,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return ChildOutcome.failed(
                request, f"child {request.child} timed out after {self.timeout_seconds}s"
            )
        except OSError as error:
            return ChildOutcome.failed(
                request, f"child {request.child} could not start: {error}"
            )

        if self.wants_result_file and result_path.is_file():
            return ChildOutcome(request.node, request.child, result_path.read_bytes())
        payload = _extract_json(completed.stdout)
        if payload is None:
            detail = (completed.stderr or completed.stdout).strip()[-self.output_limit :]
            return ChildOutcome.failed(
                request,
                f"child {request.child} produced no ChildResult "
                f"(exit {completed.returncode}): {detail}",
            )
        return ChildOutcome(request.node, request.child, payload)


def _substitute(token: str, substitutions: dict[str, str]) -> str:
    for name, value in substitutions.items():
        token = token.replace("{" + name + "}", value)
    return token


def _extract_json(stdout: str) -> bytes | None:
    """Return the last envelope-shaped JSON object printed on stdout."""
    candidates = [line.strip() for line in stdout.splitlines() if line.strip().startswith("{")]
    for candidate in reversed(candidates):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and "schema_version" in parsed:
            return candidate.encode("utf-8")
    return None
