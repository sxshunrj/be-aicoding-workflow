"""Human decision points for the orchestrator.

The helper freezes the review policy at ``init`` and refuses policy violations
itself; this module only decides *what to answer*. A non-interactive gate never
guesses: it blocks and hands control back to a human, because resume, abort,
and every ``human_review`` gate are mandatory human gates.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import sys
from typing import Protocol

from ai_workflow.errors import AppError


class GateDecision(StrEnum):
    """The human answer to one decision point."""

    ACCEPT = "accept"
    RERUN = "rerun"
    BLOCK = "block"
    RESUME = "resume"
    ABORT = "abort"


@dataclass(frozen=True, slots=True)
class GateOutcome:
    """One human answer with its optional rerun proposal."""

    decision: GateDecision
    reruns: tuple[tuple[str, str], ...] = ()
    reason: str = ""

    def rerun_map(self) -> dict[str, str]:
        return dict(self.reruns)


@dataclass(frozen=True, slots=True)
class ReviewView:
    """Everything a human needs to answer a review gate."""

    run_id: str
    phase: str
    digest: str
    decision: str
    proposed_reruns: tuple[tuple[str, str], ...]
    summary: str


@dataclass(frozen=True, slots=True)
class BlockedView:
    """Everything a human needs to answer a blocked run."""

    run_id: str
    phase: str
    reason: str


class HumanGate(Protocol):
    """Answers review gates and blocked-run decisions."""

    def review(self, view: ReviewView) -> GateOutcome:
        """Answer one ``human_review`` gate."""
        ...

    def blocked(self, view: BlockedView) -> GateOutcome:
        """Answer one blocked run: resume or abort."""
        ...


class RefusingGate:
    """Non-interactive gate: never invents a human decision.

    It answers ``BLOCK`` so the loop stops and reports the decision point. That
    is the fail-closed behaviour: an unattended run parks at the gate instead of
    accepting a review or aborting work on its own.
    """

    def review(self, view: ReviewView) -> GateOutcome:
        return GateOutcome(
            GateDecision.BLOCK,
            reason=(
                f"review gate for phase {view.phase} needs a human decision "
                f"(digest {view.digest}); re-run with an interactive gate or call "
                f"workflow review-accept --expected-digest {view.digest}"
            ),
        )

    def blocked(self, view: BlockedView) -> GateOutcome:
        return GateOutcome(
            GateDecision.BLOCK,
            reason=f"run is blocked and needs a human decision: {view.reason}",
        )


def _stderr_write(text: str = "") -> None:
    print(text, file=sys.stderr, flush=True)


def _stderr_read(prompt: str = "") -> str:
    if prompt:
        print(prompt, end="", file=sys.stderr, flush=True)
    line = sys.stdin.readline()
    if not line:
        raise AppError(
            "gate_input_unavailable",
            "interactive gate needs a human answer but stdin is closed",
        )
    return line.rstrip("\n")


class PromptHumanGate:
    """Interactive gate backed by a line-based prompt.

    The prompt and its questions go to **stderr**: the helper CLI reserves
    stdout for the single JSON envelope, so a gate that printed to stdout would
    corrupt the contract for every caller. ``read``/``write`` stay injectable so
    the decision logic is testable without a terminal.
    """

    def __init__(self, *, read=_stderr_read, write=_stderr_write) -> None:
        self._read = read
        self._write = write

    def review(self, view: ReviewView) -> GateOutcome:
        self._write(f"\nreview gate: phase={view.phase} digest={view.digest}")
        self._write(view.summary)
        if view.proposed_reruns:
            self._write("proposed reruns:")
            for node, reason in view.proposed_reruns:
                self._write(f"  {node} = {reason}")
        self._write("1) accept   2) rerun with my own proposal   3) block")
        choice = self._read("choice [1/2/3]: ").strip()
        if choice == "1":
            return GateOutcome(GateDecision.ACCEPT)
        if choice == "2":
            return GateOutcome(GateDecision.RERUN, reruns=self._ask_reruns(view.phase))
        return GateOutcome(
            GateDecision.BLOCK,
            reason=self._read("block reason: ").strip() or "human blocked at the review gate",
        )

    def blocked(self, view: BlockedView) -> GateOutcome:
        self._write(f"\nrun blocked: {view.reason}")
        self._write("1) resume   2) resume with reruns   3) abort")
        choice = self._read("choice [1/2/3]: ").strip()
        if choice == "1":
            return GateOutcome(GateDecision.RESUME)
        if choice == "2":
            return GateOutcome(GateDecision.RERUN, reruns=self._ask_reruns(view.phase))
        return GateOutcome(GateDecision.ABORT)

    def _ask_reruns(self, phase: str) -> tuple[tuple[str, str], ...]:
        self._write(f"enter one `NODE=REASON` per line for phase {phase}; empty line ends the list")
        reruns: list[tuple[str, str]] = []
        while True:
            line = self._read("rerun: ").strip()
            if not line:
                return tuple(reruns)
            try:
                reruns.append(parse_rerun_line(line))
            except AppError as error:
                self._write(error.message)


def parse_rerun_line(line: str) -> tuple[str, str]:
    """Parse one ``NODE=REASON`` line, rejecting empty halves.

    The helper validates the shape again; this only spares a round trip.
    """
    if "=" not in line:
        raise AppError("invalid_arguments", "--rerun must use NODE=REASON")
    node, reason = line.split("=", 1)
    if not node.strip():
        raise AppError("invalid_arguments", "rerun node must not be empty")
    if not reason.strip():
        raise AppError("invalid_arguments", "rerun reason must not be empty")
    return node.strip(), reason.strip()
