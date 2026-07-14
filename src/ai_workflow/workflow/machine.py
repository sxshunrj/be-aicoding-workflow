from ai_workflow.errors import AppError
from ai_workflow.workflow.models import NodeStatus, Phase, RunState


PHASE_ORDER = (Phase.SPEC, Phase.PLAN, Phase.IMPLEMENT, Phase.VERIFY)
TERMINAL_STATUSES = {"completed", "aborted"}


class StateMachine:
    def advance(self, state: RunState) -> RunState:
        self._require_changeable(state)
        if state.status == NodeStatus.BLOCKED.value:
            raise AppError("invalid_transition", "cannot advance a blocked run")
        try:
            current = Phase(state.current_phase)
            index = PHASE_ORDER.index(current)
        except (ValueError, KeyError) as error:
            raise AppError("invalid_transition", "current phase is invalid") from error
        if state.nodes[current.value].status != NodeStatus.VALID.value:
            raise AppError("invalid_transition", "current node is not valid")
        if index == len(PHASE_ORDER) - 1:
            state.status = "completed"
            return state
        state.current_phase = PHASE_ORDER[index + 1].value
        state.status = NodeStatus.PENDING.value
        return state

    def apply_reruns(self, state: RunState, reruns: dict[Phase, str]) -> RunState:
        self._require_changeable(state)
        if not reruns:
            raise AppError("invalid_transition", "at least one rerun is required")
        try:
            current_index = PHASE_ORDER.index(Phase(state.current_phase))
        except ValueError as error:
            raise AppError("invalid_transition", "current phase is invalid") from error
        for phase, reason in reruns.items():
            if phase not in PHASE_ORDER:
                raise AppError("invalid_transition", f"invalid rerun phase: {phase}")
            if PHASE_ORDER.index(phase) > current_index:
                raise AppError("invalid_transition", "cannot rerun a forward phase")
            if not reason.strip():
                raise AppError("invalid_transition", "rerun reason must not be empty")
        earliest = min(reruns, key=PHASE_ORDER.index)
        earliest_index = PHASE_ORDER.index(earliest)
        for phase in PHASE_ORDER[earliest_index:]:
            state.nodes[phase.value].status = (
                NodeStatus.RERUN.value
                if phase in reruns
                else NodeStatus.PENDING.value
            )
        state.current_phase = earliest.value
        state.status = NodeStatus.PENDING.value
        return state

    @staticmethod
    def _require_changeable(state: RunState) -> None:
        if state.status in TERMINAL_STATUSES:
            raise AppError("invalid_transition", "terminal run cannot be changed")
