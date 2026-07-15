from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Literal


UNABLE_REASON = (
    "child unable to complete; workflow must provide an actionable reason"
)


@dataclass(frozen=True, slots=True)
class ReviewDecision:
    decision: Literal["human_review", "accept"]
    run_id: str
    phase: str
    state_version: int
    proposed_reruns: tuple[tuple[str, str], ...]
    effective_reruns: tuple[tuple[str, str], ...]
    digest: str

    @classmethod
    def create(
        cls,
        *,
        decision: Literal["human_review", "accept"],
        run_id: str,
        phase: str,
        state_version: int,
        proposed_reruns: tuple[tuple[str, str], ...],
        effective_reruns: tuple[tuple[str, str], ...],
    ) -> ReviewDecision:
        unsigned = {
            "decision": decision,
            "run_id": run_id,
            "phase": phase,
            "state_version": state_version,
            "proposed_reruns": proposed_reruns,
            "effective_reruns": effective_reruns,
        }
        payload = json.dumps(
            unsigned, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return cls(
            decision=decision,
            run_id=run_id,
            phase=phase,
            state_version=state_version,
            proposed_reruns=proposed_reruns,
            effective_reruns=effective_reruns,
            digest=hashlib.sha256(payload).hexdigest(),
        )

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> ReviewDecision:
        expected = {
            "decision",
            "run_id",
            "phase",
            "state_version",
            "proposed_reruns",
            "effective_reruns",
            "digest",
        }
        if set(data) != expected:
            raise ValueError("review decision keys are invalid")
        decision = data["decision"]
        run_id = data["run_id"]
        phase = data["phase"]
        state_version = data["state_version"]
        digest = data["digest"]
        if decision not in {"human_review", "accept"}:
            raise ValueError("review decision is invalid")
        if not isinstance(run_id, str) or not run_id:
            raise ValueError("review run ID is invalid")
        if not isinstance(phase, str) or not phase:
            raise ValueError("review phase is invalid")
        if type(state_version) is not int or state_version < 1:
            raise ValueError("review state version is invalid")
        if not isinstance(digest, str):
            raise ValueError("review digest is invalid")
        proposed = cls._reruns(data["proposed_reruns"])
        effective = cls._reruns(data["effective_reruns"])
        rebuilt = cls.create(
            decision=decision,
            run_id=run_id,
            phase=phase,
            state_version=state_version,
            proposed_reruns=proposed,
            effective_reruns=effective,
        )
        if digest != rebuilt.digest:
            raise ValueError("review digest is invalid")
        return rebuilt

    @staticmethod
    def _reruns(value: object) -> tuple[tuple[str, str], ...]:
        if not isinstance(value, (list, tuple)):
            raise ValueError("review reruns are invalid")
        items: list[tuple[str, str]] = []
        for item in value:
            if (
                not isinstance(item, (list, tuple))
                or len(item) != 2
                or not isinstance(item[0], str)
                or not isinstance(item[1], str)
            ):
                raise ValueError("review reruns are invalid")
            items.append((item[0], item[1]))
        return tuple(items)

    def to_dict(self) -> dict[str, object]:
        return {
            "decision": self.decision,
            "run_id": self.run_id,
            "phase": self.phase,
            "state_version": self.state_version,
            "proposed_reruns": [list(item) for item in self.proposed_reruns],
            "effective_reruns": [list(item) for item in self.effective_reruns],
            "digest": self.digest,
        }
