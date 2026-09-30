"""Code-owned orchestrator for ai-workflow runs.

The Skill-first product lets the main agent drive the helper CLI by following
markdown. This package moves the *mechanical* half of that loop into code: it
dispatches children, stages their results, settles barriers, runs the phase
commands itself as evidence, and stops at the human gates.

The semantic half stays where it belongs. Rerun proposals come from a pluggable
proposer, so a deployment can keep them model-authored while the loop, the
gating, and the evidence stay deterministic.
"""

from ai_workflow.harness.evidence import EvidenceRecord, EvidenceRecorder
from ai_workflow.harness.gates import (
    GateDecision,
    GateOutcome,
    HumanGate,
    PromptHumanGate,
    RefusingGate,
)
from ai_workflow.harness.loop import DeterministicProposer, LoopEvent, RunLoop, RunOutcome
from ai_workflow.harness.runner import ChildOutcome, ChildRequest, ChildRunner, SubprocessChildRunner

__all__ = [
    "ChildOutcome",
    "ChildRequest",
    "ChildRunner",
    "DeterministicProposer",
    "EvidenceRecord",
    "EvidenceRecorder",
    "GateDecision",
    "GateOutcome",
    "HumanGate",
    "LoopEvent",
    "PromptHumanGate",
    "RefusingGate",
    "RunLoop",
    "RunOutcome",
    "SubprocessChildRunner",
]
