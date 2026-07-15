from collections.abc import Iterable

from ai_workflow.errors import AppError
from ai_workflow.workflow.graph import NodeValidity, RunGraphNode
from ai_workflow.workflow.models import NodeStatus, Phase, RunState


PHASE_ORDER = (Phase.SPEC, Phase.PLAN, Phase.IMPLEMENT, Phase.VERIFY)
TERMINAL_STATUSES = {"completed", "aborted"}


def phase_nodes(state: RunState, phase: Phase) -> tuple[RunGraphNode, ...]:
    return tuple(node for node in state.run_graph.values() if node.phase is phase)


def phase_is_valid(state: RunState, phase: Phase) -> bool:
    nodes = phase_nodes(state, phase)
    return bool(nodes) and all(node.validity is NodeValidity.VALID for node in nodes)


def earliest_phase(keys: Iterable[str]) -> Phase:
    phases = {Phase(key.split(".", 1)[0]) for key in keys}
    if not phases:
        raise AppError("invalid_transition", "at least one rerun node is required")
    return min(phases, key=PHASE_ORDER.index)


class StateMachine:
    def advance(self, state: RunState) -> RunState:
        self._require_changeable(state)
        if state.status == NodeStatus.BLOCKED.value:
            raise AppError("invalid_transition", "cannot advance a blocked run")
        try:
            current = Phase(state.current_phase)
            index = PHASE_ORDER.index(current)
        except ValueError as error:
            raise AppError("invalid_transition", "current phase is invalid") from error
        if not phase_is_valid(state, current):
            raise AppError("invalid_transition", "current phase is not valid")
        if index == len(PHASE_ORDER) - 1:
            state.status = "completed"
            return state
        state.current_phase = PHASE_ORDER[index + 1].value
        state.status = NodeStatus.PENDING.value
        return state

    def apply_reruns(self, state: RunState, reruns: dict[str, str]) -> RunState:
        self._require_changeable(state)
        try:
            current_index = PHASE_ORDER.index(Phase(state.current_phase))
        except ValueError as error:
            raise AppError("invalid_transition", "current phase is invalid") from error
        for key, reason in reruns.items():
            node = state.run_graph.get(key)
            if node is None:
                raise AppError("invalid_transition", f"unknown rerun node: {key}")
            if PHASE_ORDER.index(node.phase) > current_index:
                raise AppError("invalid_transition", "cannot rerun a forward phase")
            if not isinstance(reason, str) or not reason.strip():
                raise AppError(
                    "invalid_transition", "rerun reason must not be empty"
                )

        earliest = earliest_phase(reruns)
        earliest_index = PHASE_ORDER.index(earliest)
        for node in state.run_graph.values():
            if PHASE_ORDER.index(node.phase) > earliest_index:
                node.validity = NodeValidity.PENDING
                node.reason = None
        for key, reason in reruns.items():
            node = state.run_graph[key]
            node.validity = NodeValidity.RERUN
            node.reason = reason
        state.current_phase = earliest.value
        state.status = NodeStatus.PENDING.value
        return state

    @staticmethod
    def _require_changeable(state: RunState) -> None:
        if state.status in TERMINAL_STATUSES:
            raise AppError("invalid_transition", "terminal run cannot be changed")
