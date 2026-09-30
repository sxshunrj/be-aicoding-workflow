"""The orchestrator loop.

It owns the mechanical sequence the Skill describes in prose:

``status -> begin -> dispatch -> stage -> barrier -> finalize -> review ->
gate -> transition -> status``

Everything that requires judgement stays pluggable: the proposer decides which
nodes must rerun, and the gate answers the human decision points. The loop
itself never edits state, never repairs a child result, and never guesses an
answer on a human's behalf.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from ai_workflow.config import RepositoryConfig
from ai_workflow.errors import AppError
from ai_workflow.harness.evidence import EvidenceRecord, EvidenceRecorder
from ai_workflow.harness.gates import (
    BlockedView,
    GateDecision,
    HumanGate,
    ReviewView,
)
from ai_workflow.harness.runner import ChildOutcome, ChildRequest, ChildRunner
from ai_workflow.workflow.models import Phase
from ai_workflow.workflow.service import PhaseAggregate, PhaseAttempt, WorkflowService

TERMINAL_STATUSES = {"completed", "aborted"}
BLOCKED_STATUS = "blocked"

# Reasons must be actionable; the helper rejects its own placeholder, so the
# orchestrator must never synthesize it either.
UNABLE_REASON_PREFIX = "child reported unable_to_complete"


@dataclass(frozen=True, slots=True)
class LoopEvent:
    """One observable step of the loop, for logs and tests."""

    kind: str
    data: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RunOutcome:
    """How the loop stopped."""

    run_id: str
    status: str
    steps: int
    events: tuple[LoopEvent, ...]
    stopped_reason: str = ""


class Proposer(Protocol):
    """Decides the rerun proposal handed to the review gate."""

    def propose(
        self,
        *,
        phase: Phase,
        attempt: PhaseAttempt,
        aggregate: PhaseAggregate,
        evidence: Sequence[EvidenceRecord],
    ) -> dict[str, str]:
        """Return ``NODE=REASON`` entries; empty means "accept this phase"."""
        ...


class DeterministicProposer:
    """Propose reruns from evidence alone, with no model in the loop.

    Two rules, both mechanical:

    * a child that reported ``unable_to_complete`` reruns its own node;
    * a node whose configured command the harness observed failing reruns,
      even when its child reported success.

    The second rule is the point of harness-owned evidence: a child cannot talk
    its way past a non-zero exit status the harness saw itself.
    """

    def propose(
        self,
        *,
        phase: Phase,
        attempt: PhaseAttempt,
        aggregate: PhaseAggregate,
        evidence: Sequence[EvidenceRecord],
    ) -> dict[str, str]:
        node_of_child = {item.child: item.node for item in attempt.dispatch_plan}
        reruns: dict[str, str] = {}
        for child in aggregate.children:
            name = child.get("child")
            status = child.get("status")
            if not isinstance(name, str) or status != "unable_to_complete":
                continue
            node = str(child.get("node") or node_of_child.get(name) or f"{phase.value}.{name}")
            reruns[node] = (
                f"{UNABLE_REASON_PREFIX}: {name} did not produce a usable artifact this attempt; "
                f"re-run {name} and address the reported finding"
            )
        for record in evidence:
            if record.passed or record.node in reruns:
                continue
            reruns[record.node] = (
                f"harness observed exit {record.exit_status} for "
                f"`{' '.join(record.argv)}`; fix the failure or correct the command, "
                f"then re-run {record.child} (evidence: {record.path})"
            )
        return reruns


class RunLoop:
    """Drive one run to a terminal status or to a human decision point."""

    def __init__(
        self,
        service: WorkflowService,
        runner: ChildRunner,
        gate: HumanGate,
        *,
        skill_dir: Path | None = None,
        proposer: Proposer | None = None,
        evidence: EvidenceRecorder | None = None,
        max_steps: int = 200,
        on_event: Callable[[LoopEvent], None] | None = None,
    ) -> None:
        self.service = service
        self.runner = runner
        self.gate = gate
        self.skill_dir = skill_dir
        self.proposer = proposer or DeterministicProposer()
        self.evidence = evidence
        self.max_steps = max_steps
        self.on_event = on_event

    def run(self, run_id: str) -> RunOutcome:
        """Advance ``run_id`` until terminal or until a human answer is required."""
        events: list[LoopEvent] = []

        def emit(kind: str, **data: object) -> None:
            event = LoopEvent(kind, data)
            events.append(event)
            if self.on_event is not None:
                self.on_event(event)

        for step in range(1, self.max_steps + 1):
            state = self.service.status(run_id)
            if state.status in TERMINAL_STATUSES:
                emit("terminal", status=state.status, phase=state.current_phase)
                return RunOutcome(run_id, state.status, step - 1, tuple(events))
            if state.status == BLOCKED_STATUS:
                outcome = self.gate.blocked(self._blocked_view(state))
                if outcome.decision in (GateDecision.RESUME, GateDecision.RERUN):
                    emit("resume", reruns=dict(outcome.reruns))
                    self.service.resume(run_id, outcome.rerun_map() or None)
                    continue
                if outcome.decision == GateDecision.ABORT:
                    emit("abort")
                    self.service.abort(run_id)
                    continue
                emit("blocked_waiting_for_human", reason=outcome.reason)
                return RunOutcome(run_id, BLOCKED_STATUS, step - 1, tuple(events))

            phase = Phase(state.current_phase)
            attempt = self.service.begin(run_id, phase, self.skill_dir)
            emit("begin", phase=phase.value, attempt_id=attempt.attempt_id)

            owned = [
                item for item in attempt.dispatch_plan if item.execution_kind != "child_backed"
            ]
            if owned:
                # A workflow-owned node is authored by the owner itself (the Grill PRD is
                # the only one today). The loop cannot invent that artifact, and staging a
                # substitute would defeat the ownership rule, so it stops and says so.
                names = ", ".join(item.child for item in owned)
                emit("owner_input_required", children=names, attempt_id=attempt.attempt_id)
                return RunOutcome(
                    run_id,
                    state.status,
                    step,
                    tuple(events),
                    f"workflow-owned node(s) {names} need the owner to supply an artifact: "
                    f"workflow stage-owned --repo <repo> --run-id {run_id} "
                    f"--attempt-id {attempt.attempt_id} --phase {phase.value} --child <child> "
                    f"--artifact <file> --summary <text>",
                )

            if not self._run_children(emit, run_id, attempt):
                # A child produced no result: the loop parked the run and returns.
                return RunOutcome(run_id, BLOCKED_STATUS, step, tuple(events))

            evidence = self._collect_evidence(run_id, attempt)
            aggregate = self.service.finalize(run_id, attempt.attempt_id)
            emit(
                "finalize",
                attempt_id=attempt.attempt_id,
                status=aggregate.status,
                children=len(aggregate.children),
            )

            proposal = self.proposer.propose(
                phase=phase, attempt=attempt, aggregate=aggregate, evidence=evidence
            )
            decision = self.service.review(run_id, proposal)
            emit(
                "review",
                phase=phase.value,
                decision=decision.decision,
                digest=decision.digest,
                reruns=dict(decision.effective_reruns),
            )

            if decision.decision == "human_review":
                outcome = self.gate.review(self._review_view(state.run_id, decision, aggregate))
                if outcome.decision == GateDecision.RERUN:
                    proposal = dict(outcome.reruns)
                    decision = self.service.review(run_id, proposal)
                    emit("review", phase=phase.value, decision=decision.decision,
                         digest=decision.digest, reruns=dict(decision.effective_reruns))
                elif outcome.decision == GateDecision.BLOCK:
                    reason = outcome.reason or "human blocked at the review gate"
                    self.service.block(run_id, reason)
                    emit("block", reason=reason)
                    continue
                elif outcome.decision == GateDecision.ABORT:
                    self.service.abort(run_id)
                    emit("abort")
                    continue
                self.service.record_review_acceptance(run_id, decision.digest)
                emit("review_accepted", digest=decision.digest)

            self.service.transition(run_id)
            emit("transition", phase=phase.value)

        raise AppError(
            "harness_step_limit",
            f"run {run_id} did not reach a decision point within {self.max_steps} steps",
        )

    def _run_children(self, emit: Callable[..., None], run_id: str, attempt: PhaseAttempt) -> bool:
        """Run and stage every dispatch item. Returns False when the run was parked."""
        for item in attempt.dispatch_plan:
            if item.action == "already_staged":
                emit("already_staged", child=item.child, node=item.node)
                continue
            request = ChildRequest(
                node=item.node,
                child=item.child,
                action=item.action,
                prompt_file=item.prompt_file,
                packet_file=item.packet_file,
            )
            if item.execution_kind != "child_backed":
                raise AppError(
                    "invalid_dispatch",
                    f"workflow-owned node {item.node} reached child dispatch",
                )
            result_path = self._result_path(run_id, attempt.attempt_id, item.child)
            outcome = self.runner.run(request, result_path)
            if not outcome.ok:
                reason = outcome.failure or f"child {item.child} produced no ChildResult"
                self.service.block(run_id, f"{request.node}: {reason}")
                emit("child_failed", child=item.child, node=item.node, reason=reason)
                return False
            payload = outcome.result_bytes
            assert payload is not None
            result_path.parent.mkdir(parents=True, exist_ok=True)
            result_path.write_bytes(payload)
            self.service.stage(run_id, attempt.attempt_id, item.child, result_path)
            emit("stage", child=item.child, node=item.node, result=str(result_path))
        return True

    def _collect_evidence(self, run_id: str, attempt: PhaseAttempt) -> tuple[EvidenceRecord, ...]:
        """Run the configured command for every child that has one."""
        if self.evidence is None or self.service.repo_root is None:
            return ()
        config = RepositoryConfig.load(self.service.repo_root)
        records: list[EvidenceRecord] = []
        for item in attempt.dispatch_plan:
            command = config.command(item.child)
            if command is None:
                continue
            records.append(
                self.evidence.record(
                    run_id=run_id,
                    attempt_id=attempt.attempt_id,
                    node=item.node,
                    child=item.child,
                    command=command,
                    cwd=self.service.repo_root,
                )
            )
        return tuple(records)

    def _result_path(self, run_id: str, attempt_id: str, child: str) -> Path:
        if self.service.repo_root is None:
            raise AppError("repository_required", "repository root is required to run children")
        # Keep harness scratch inside the run subtree: the checkpoint excludes
        # `.ai-workflow/runs/` wholesale, so result files never enter a checkpoint.
        return (
            self.service.harness_directory(run_id)
            / "results"
            / attempt_id
            / f"{child}.json"
        )

    @staticmethod
    def _review_view(run_id: str, decision, aggregate: PhaseAggregate) -> ReviewView:
        return ReviewView(
            run_id=run_id,
            phase=decision.phase,
            digest=decision.digest,
            decision=decision.decision,
            proposed_reruns=decision.proposed_reruns,
            summary=(
                f"phase {decision.phase}: {len(aggregate.children)} child result(s), "
                f"aggregate status {aggregate.status}"
            ),
        )

    @staticmethod
    def _blocked_view(state) -> BlockedView:
        return BlockedView(
            run_id=state.run_id,
            phase=state.current_phase,
            reason=RunLoop._blocked_reason(state),
        )

    @staticmethod
    def _blocked_reason(state) -> str:
        """Recover why the run is blocked.

        ``_blocked_state`` only stores the prior run status and phase, so the
        reason comes from the last lifecycle operation's input, or from the
        checkpoint failure that forced the block.
        """
        operation = state.artifacts.get("_lifecycle_operation")
        if isinstance(operation, Mapping):
            payload = operation.get("input")
            if isinstance(payload, Mapping):
                reason = payload.get("reason")
                if isinstance(reason, str) and reason.strip():
                    return reason
        failure = state.artifacts.get("_checkpoint_failure")
        if isinstance(failure, Mapping):
            message = failure.get("message")
            if isinstance(message, str) and message.strip():
                return f"checkpoint failure ({failure.get('code')}): {message}"
        return f"run blocked in phase {state.current_phase}; see the run events for the recorded reason"
