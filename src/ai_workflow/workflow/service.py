from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re
from uuid import uuid4

import yaml

from ai_workflow.config import RepositoryConfig
from ai_workflow.errors import AppError
from ai_workflow.workflow.machine import StateMachine
from ai_workflow.workflow.models import NodeStatus, Phase, RunState
from ai_workflow.workflow.store import Event, StateStore


RUN_ID_PATTERN = re.compile(r"RUN-\d{8}-\d{6}-[0-9a-f]{6}")
ID_SUFFIX_PATTERN = re.compile(r"[0-9a-f]{6}")
BLOCKED_STATE_KEY = "_blocked_state"


@dataclass(frozen=True, slots=True)
class Attempt:
    run_id: str
    phase: str
    number: int

    def to_dict(self) -> dict[str, object]:
        return {"run_id": self.run_id, "phase": self.phase, "number": self.number}


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
        node.status = NodeStatus.RUNNING.value
        state.status = NodeStatus.RUNNING.value
        self._save(state, "phase_begun", {"phase": phase.value, "attempt": number})
        return Attempt(run_id, phase.value, number)

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
        run_path = (runs_root / run_id).resolve()
        if run_path.parent != runs_root:
            raise AppError("invalid_run_id", "run path escapes workflow storage")
        return StateStore(run_path)

    def _load(self, run_id: str) -> RunState:
        try:
            return self._store(run_id).load()
        except FileNotFoundError as error:
            raise AppError("state_not_found", f"workflow run not found: {run_id}") from error
        except (yaml.YAMLError, KeyError, TypeError, ValueError, UnicodeError) as error:
            raise AppError("invalid_state", "workflow state is malformed") from error

    def _save(self, state: RunState, event_type: str, data: dict[str, object]) -> None:
        self._store(state.run_id).save(state.version, state, Event(event_type, data))
