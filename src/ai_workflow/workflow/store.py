from dataclasses import dataclass
import json
import os
from pathlib import Path
from uuid import uuid4

import yaml

from ai_workflow.errors import AppError
from ai_workflow.workflow.models import RunState


@dataclass(frozen=True, slots=True)
class Event:
    type: str
    data: dict[str, object]


class StateStore:
    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir
        self.state_path = run_dir / "state.yaml"
        self.events_path = run_dir / "events.jsonl"

    def create(self, state: RunState) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        state_temporary = self._temporary_path(self.state_path)
        events_temporary = self._temporary_path(self.events_path)
        try:
            self._write_state(state_temporary, state)
            events_temporary.write_text("", encoding="utf-8")
            try:
                os.link(state_temporary, self.state_path)
            except FileExistsError as error:
                raise AppError("state_exists", "workflow state already exists") from error
            events_temporary.replace(self.events_path)
        finally:
            state_temporary.unlink(missing_ok=True)
            events_temporary.unlink(missing_ok=True)

    def load(self) -> RunState:
        data = yaml.safe_load(self.state_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise AppError("invalid_state", "workflow state must be a mapping")
        return RunState.from_dict(data)

    def save(self, expected_version: int, state: RunState, event: Event) -> None:
        current = self.load()
        if current.version != expected_version:
            raise AppError(
                "stale_state",
                "state version changed; reload before writing",
                exit_status=4,
            )
        state.version = expected_version + 1
        temporary = self.state_path.with_suffix(".yaml.tmp")
        self._write_state(temporary, state)
        temporary.replace(self.state_path)
        with self.events_path.open("a", encoding="utf-8") as stream:
            stream.write(
                json.dumps(
                    {"type": event.type, "version": state.version, "data": event.data},
                    separators=(",", ":"),
                )
                + "\n"
            )

    @staticmethod
    def _write_state(path: Path, state: RunState) -> None:
        path.write_text(
            yaml.safe_dump(state.to_dict(), sort_keys=False),
            encoding="utf-8",
        )

    @staticmethod
    def _temporary_path(path: Path) -> Path:
        return path.with_name(f".{path.name}.{uuid4().hex}.tmp")
