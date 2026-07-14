from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re
from uuid import uuid4
import hashlib
import json

import yaml

from ai_workflow.config import RepositoryConfig
from ai_workflow.contracts.artifacts import ArtifactRef, ChildResult
from ai_workflow.contracts.packets import PhasePacket
from ai_workflow.errors import AppError
from ai_workflow.workflow.machine import StateMachine
from ai_workflow.workflow.models import NodeStatus, Phase, RunState
from ai_workflow.workflow.store import Event, StateStore


RUN_ID_PATTERN = re.compile(r"RUN-\d{8}-\d{6}-[0-9a-f]{6}")
ID_SUFFIX_PATTERN = re.compile(r"[0-9a-f]{6}")
BLOCKED_STATE_KEY = "_blocked_state"
RUN_STATUSES = {
    NodeStatus.PENDING.value,
    NodeStatus.RUNNING.value,
    NodeStatus.BLOCKED.value,
    "completed",
    "aborted",
}
NODE_STATUSES = {status.value for status in NodeStatus}
RESTORABLE_RUN_STATUSES = {NodeStatus.PENDING.value, NodeStatus.RUNNING.value}
RESTORABLE_NODE_STATUSES = {
    NodeStatus.PENDING.value,
    NodeStatus.RUNNING.value,
    NodeStatus.RERUN.value,
}


@dataclass(frozen=True, slots=True)
class Attempt:
    run_id: str
    phase: str
    number: int
    attempt_id: str
    packet_path: str

    def to_dict(self) -> dict[str, object]:
        return {"run_id": self.run_id, "phase": self.phase, "number": self.number,
                "attempt_id": self.attempt_id, "packet_path": self.packet_path}


@dataclass(frozen=True, slots=True)
class RunSummary:
    run_id: str
    phase_durations_ms: dict[str, int]
    attempt_count: int
    rerun_count: int
    review_gate_decisions: tuple[dict[str, object], ...]
    cited_knowledge_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {"run_id": self.run_id, "phase_durations_ms": self.phase_durations_ms,
                "attempt_count": self.attempt_count, "rerun_count": self.rerun_count,
                "review_gate_decisions": list(self.review_gate_decisions),
                "cited_knowledge_ids": list(self.cited_knowledge_ids)}


class WorkflowService:
    def __init__(
        self,
        repo_root: Path | None = None,
        *,
        clock: Callable[[], datetime] = datetime.now,
        id_factory: Callable[[], str] = lambda: uuid4().hex[:6],
    ) -> None:
        self.repo_root = repo_root
        self.clock = clock
        self.id_factory = id_factory
        self.machine = StateMachine()

    def init(self, repo_root: Path, source_revision: str) -> RunState:
        RepositoryConfig.load(repo_root)
        if not source_revision.strip():
            raise AppError("invalid_source_revision", "source revision must not be empty")
        self.repo_root = repo_root
        suffix = str(self.id_factory())
        if ID_SUFFIX_PATTERN.fullmatch(suffix) is None:
            raise AppError(
                "invalid_run_id",
                "generated run ID suffix must be six lowercase hex characters",
            )
        run_id = f"RUN-{self.clock():%Y%m%d-%H%M%S}-{suffix}"
        state = RunState.new(run_id, source_revision)
        self._store(run_id).create(state)
        return state

    def status(self, run_id: str) -> RunState:
        return self._load(run_id)

    def begin(self, run_id: str, phase: Phase) -> Attempt:
        state = self._load(run_id)
        self._active(state)
        if state.current_phase != phase.value:
            raise AppError("invalid_transition", "cannot skip workflow phases")
        node = state.nodes[phase.value]
        if node.status not in {NodeStatus.PENDING.value, NodeStatus.RERUN.value}:
            raise AppError("invalid_transition", "phase cannot be begun in its current state")
        attempts = state.artifacts.setdefault("attempts", {})
        if not isinstance(attempts, dict):
            raise AppError("invalid_state", "attempt metadata is invalid")
        number = int(attempts.get(phase.value, 0)) + 1
        if self.repo_root is None:
            raise AppError("repository_required", "repository root is required")
        if number > RepositoryConfig.load(self.repo_root).max_attempts:
            raise AppError("attempt_limit", "maximum attempts reached for phase")
        attempts[phase.value] = number
        attempt_id = f"{phase.value}-{number}-{self.id_factory()}"
        current_attempts = state.artifacts.setdefault("current_attempts", {})
        if not isinstance(current_attempts, dict):
            raise AppError("invalid_state", "current attempt metadata is invalid")
        current_attempts[phase.value] = attempt_id
        node.status = NodeStatus.RUNNING.value
        state.status = NodeStatus.RUNNING.value
        packet_path = self._store(run_id).run_dir / "attempts" / attempt_id / "phase-packet.json"
        prior = self._artifact_refs(state)
        rerun_reasons = state.artifacts.get("rerun_reasons", {})
        rerun_reason = rerun_reasons.get(phase.value) if isinstance(rerun_reasons, dict) else None
        PhasePacket(run_id, phase, attempt_id, state.source_revision, {}, prior,
                    rerun_reason if isinstance(rerun_reason, str) else None).write(packet_path)
        self._save(state, "phase_begun", {"phase": phase.value, "attempt": number,
                                          "attempt_id": attempt_id, "packet_path": str(packet_path)})
        return Attempt(run_id, phase.value, number, attempt_id, str(packet_path))

    def submit(self, run_id: str, attempt_id: str, result_path: Path) -> RunState:
        state = self._load(run_id)
        current = state.artifacts.get("current_attempts", {})
        accepted = state.artifacts.get("accepted_results", {})
        if not isinstance(current, dict) or not isinstance(accepted, dict):
            raise AppError("invalid_state", "attempt result metadata is invalid")
        previous = accepted.get(attempt_id)
        try:
            raw_result = result_path.read_bytes()
            result_digest = hashlib.sha256(raw_result).hexdigest()
            result = ChildResult.load(result_path)
        except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            raise AppError("invalid_result", f"child result is invalid: {error}") from error
        if previous is not None:
            if previous == result_digest:
                return state
            raise AppError("result_conflict", "attempt already has a different accepted result")
        matching = [name for name, owner in current.items() if owner == attempt_id]
        if len(matching) != 1:
            raise AppError("attempt_owner_mismatch", "result does not belong to the current attempt")
        phase = Phase(matching[0])
        if state.current_phase != phase.value or state.nodes[phase.value].status != NodeStatus.RUNNING.value:
            raise AppError("attempt_owner_mismatch", "result does not belong to the running phase")
        artifact = result.artifact
        if result.status == "completed" and artifact is None:
            raise AppError("invalid_result", "completed result requires an artifact")
        if artifact is not None:
            self._validate_artifact(state, phase, artifact, result_path)
            artifacts = state.artifacts.setdefault("registered", [])
            if not isinstance(artifacts, list):
                raise AppError("invalid_state", "artifact registry is invalid")
            artifacts.append(artifact.to_dict())
        accepted[attempt_id] = result_digest
        state.artifacts["accepted_results"] = accepted
        if result.status == "completed":
            state.nodes[phase.value].status = NodeStatus.VALID.value
            self.machine.advance(state)
        else:
            state.nodes[phase.value].status = NodeStatus.RERUN.value
            state.status = NodeStatus.PENDING.value
        self._save(state, "result_submitted", {"phase": phase.value, "attempt_id": attempt_id,
                                                "result_digest": result_digest, "status": result.status,
                                                "summary": result.summary,
                                                "artifact": None if artifact is None else artifact.to_dict()})
        return state

    def _validate_artifact(self, state: RunState, phase: Phase, artifact: ArtifactRef,
                           result_path: Path) -> None:
        if artifact.phase != phase:
            raise AppError("invalid_result", "artifact phase does not match attempt")
        if artifact.source_revision != state.source_revision:
            raise AppError("invalid_result", "artifact source revision does not match run")
        path = Path(artifact.path)
        if not path.is_absolute():
            path = result_path.parent / path
        if self.repo_root is None:
            raise AppError("repository_required", "repository root is required")
        try:
            path.resolve().relative_to(self.repo_root.resolve())
        except ValueError as error:
            raise AppError("invalid_result", "artifact path escapes repository") from error
        if path.is_symlink() or not path.is_file():
            raise AppError("invalid_result", "artifact path must be a regular file")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(65536), b""):
                digest.update(chunk)
        if digest.hexdigest() != artifact.sha256:
            raise AppError("artifact_digest_mismatch", "artifact digest does not match result")

    @staticmethod
    def _artifact_refs(state: RunState) -> tuple[ArtifactRef, ...]:
        raw = state.artifacts.get("registered", [])
        if not isinstance(raw, list):
            raise AppError("invalid_state", "artifact registry is invalid")
        try:
            return tuple(ArtifactRef.from_dict(item) for item in raw if isinstance(item, dict))
        except (ValueError, TypeError, KeyError) as error:
            raise AppError("invalid_state", "artifact registry is invalid") from error

    def summary(self, run_id: str) -> RunSummary:
        self._load(run_id)
        events = []
        try:
            for line in self._store(run_id).events_path.read_text(encoding="utf-8").splitlines():
                events.append(json.loads(line))
        except (OSError, json.JSONDecodeError, TypeError) as error:
            raise AppError("invalid_state", "workflow events are malformed") from error
        attempts = [event for event in events if event.get("type") == "phase_begun"]
        submissions = [event for event in events if event.get("type") == "result_submitted"]
        durations: dict[str, int] = {}
        for begun in attempts:
            data = begun.get("data", {})
            if not isinstance(data, dict):
                continue
            finished = next((event for event in submissions
                             if isinstance(event.get("data"), dict)
                             and event["data"].get("attempt_id") == data.get("attempt_id")), None)
            if finished and isinstance(begun.get("timestamp"), str) and isinstance(finished.get("timestamp"), str):
                start = datetime.fromisoformat(begun["timestamp"])
                end = datetime.fromisoformat(finished["timestamp"])
                phase = str(data.get("phase"))
                durations[phase] = durations.get(phase, 0) + int((end - start).total_seconds() * 1000)
        transitions = [event["data"] for event in events if event.get("type") == "workflow_transitioned"
                       and isinstance(event.get("data"), dict)]
        cited: set[str] = set()
        for packet in self._store(run_id).run_dir.glob("attempts/*/phase-packet.json"):
            try:
                knowledge = json.loads(packet.read_text(encoding="utf-8")).get("knowledge_packet", {})
                ids = knowledge.get("cited_knowledge_ids", []) if isinstance(knowledge, dict) else []
                cited.update(str(item) for item in ids)
            except (OSError, json.JSONDecodeError, TypeError):
                continue
        return RunSummary(run_id, durations, len(attempts),
                          sum(1 for item in submissions if item["data"].get("status") == "unable_to_complete")
                          + sum(len(item.get("reruns", {})) for item in transitions),
                          tuple(transitions), tuple(sorted(cited)))

    def transition(
        self, run_id: str, accepted: bool, reruns: dict[Phase, str]
    ) -> RunState:
        state = self._load(run_id)
        self._active(state)
        phase = Phase(state.current_phase)
        if state.nodes[phase.value].status != NodeStatus.RUNNING.value:
            raise AppError("invalid_transition", "current node is not running")
        if accepted:
            if reruns:
                raise AppError("invalid_transition", "accepted transition cannot include reruns")
            state.nodes[phase.value].status = NodeStatus.VALID.value
            self.machine.advance(state)
        else:
            self.machine.apply_reruns(state, reruns)
            state.artifacts["rerun_reasons"] = {key.value: value for key, value in reruns.items()}
        self._save(
            state,
            "workflow_transitioned",
            {"accepted": accepted, "reruns": {key.value: value for key, value in reruns.items()}},
        )
        return state

    def block(self, run_id: str, reason: str) -> RunState:
        state = self._load(run_id)
        self._active(state)
        if not reason.strip():
            raise AppError("invalid_transition", "block reason must not be empty")
        state.artifacts[BLOCKED_STATE_KEY] = {
            "run": state.status,
            "node": state.nodes[state.current_phase].status,
        }
        state.status = NodeStatus.BLOCKED.value
        state.nodes[state.current_phase].status = NodeStatus.BLOCKED.value
        self._save(state, "run_blocked", {"reason": reason})
        return state

    def resume(self, run_id: str) -> RunState:
        state = self._load(run_id)
        if state.status != NodeStatus.BLOCKED.value:
            raise AppError("invalid_transition", "only a blocked run can be resumed")
        prior = state.artifacts.pop(BLOCKED_STATE_KEY, None)
        if (
            not isinstance(prior, dict)
            or not isinstance(prior.get("run"), str)
            or not isinstance(prior.get("node"), str)
        ):
            raise AppError("invalid_state", "blocked lifecycle metadata is invalid")
        state.status = prior["run"]
        state.nodes[state.current_phase].status = prior["node"]
        self._save(state, "run_resumed", {})
        return state

    def abort(self, run_id: str) -> RunState:
        state = self._load(run_id)
        self._active(state)
        state.status = "aborted"
        self._save(state, "run_aborted", {})
        return state

    def _active(self, state: RunState) -> None:
        if state.status in {"completed", "aborted"}:
            raise AppError("invalid_transition", "terminal run cannot be changed")
        if state.status == NodeStatus.BLOCKED.value:
            raise AppError("invalid_transition", "blocked run must be resumed first")

    def _store(self, run_id: str) -> StateStore:
        if self.repo_root is None:
            raise AppError("repository_required", "repository root is required")
        if RUN_ID_PATTERN.fullmatch(run_id) is None:
            raise AppError("invalid_run_id", "run ID has an invalid format")
        runs_root = (self.repo_root / ".ai-workflow" / "runs").resolve()
        run_entry = runs_root / run_id
        if run_entry.is_symlink():
            raise AppError("invalid_run_id", "run directory must not be a symlink")
        run_path = run_entry.resolve()
        if run_path.parent != runs_root:
            raise AppError("invalid_run_id", "run path escapes workflow storage")
        return StateStore(run_path)

    def _load(self, run_id: str) -> RunState:
        try:
            state = self._store(run_id).load()
        except FileNotFoundError as error:
            raise AppError("state_not_found", f"workflow run not found: {run_id}") from error
        except (yaml.YAMLError, KeyError, TypeError, ValueError, UnicodeError) as error:
            raise AppError("invalid_state", "workflow state is malformed") from error
        self._validate_state(state, run_id)
        return state

    @staticmethod
    def _validate_state(state: RunState, requested_run_id: str) -> None:
        if state.run_id != requested_run_id:
            raise AppError(
                "invalid_state",
                "persisted run ID does not match requested run ID",
            )
        try:
            current_phase = Phase(state.current_phase)
        except ValueError as error:
            raise AppError("invalid_state", "current phase is invalid") from error
        formal_phases = {phase.value for phase in Phase}
        if set(state.nodes) != formal_phases:
            raise AppError("invalid_state", "workflow nodes are incomplete or unknown")
        for phase in Phase:
            node = state.nodes[phase.value]
            if node.phase != phase.value or node.status not in NODE_STATUSES:
                raise AppError("invalid_state", f"node {phase.value} is invalid")
        if state.status not in RUN_STATUSES:
            raise AppError("invalid_state", "run status is invalid")
        attempts = state.artifacts.get("attempts", {})
        if not isinstance(attempts, dict):
            raise AppError("invalid_state", "attempt metadata is invalid")
        for phase, count in attempts.items():
            if phase not in formal_phases or type(count) is not int or count < 0:
                raise AppError("invalid_state", "attempt counter is invalid")
        blocked_state = state.artifacts.get(BLOCKED_STATE_KEY)
        if state.status == NodeStatus.BLOCKED.value:
            if state.nodes[current_phase.value].status != NodeStatus.BLOCKED.value:
                raise AppError("invalid_state", "blocked current node is invalid")
            if not isinstance(blocked_state, dict):
                raise AppError("invalid_state", "blocked lifecycle metadata is invalid")
            if (
                blocked_state.get("run") not in RESTORABLE_RUN_STATUSES
                or blocked_state.get("node") not in RESTORABLE_NODE_STATUSES
            ):
                raise AppError("invalid_state", "blocked lifecycle metadata is invalid")
        elif blocked_state is not None:
            raise AppError("invalid_state", "unexpected blocked lifecycle metadata")

    def _save(self, state: RunState, event_type: str, data: dict[str, object]) -> None:
        self._store(state.run_id).save(state.version, state, Event(event_type, data,
                                                                   self.clock().isoformat()))
