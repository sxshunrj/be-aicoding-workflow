from dataclasses import dataclass
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
from uuid import uuid4

import yaml

from ai_workflow.errors import AppError
from ai_workflow.workflow.models import RunState, validate_plain_value


@dataclass(frozen=True, slots=True)
class Event:
    type: str
    data: dict[str, object]
    timestamp: str | None = None


class StateStore:
    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir
        self.state_path = run_dir / "state.yaml"
        self.events_path = run_dir / "events.jsonl"
        self.events_lock_path = run_dir / "events.lock"

    def attempt_dir(self, attempt_id: str) -> Path:
        self._validate_component(attempt_id, "attempt ID")
        return self._safe_path("attempts", attempt_id)

    def staged_path(self, attempt_id: str, child: str) -> Path:
        self._validate_component(attempt_id, "attempt ID")
        self._validate_component(child, "child")
        return self._safe_path("attempts", attempt_id, "staged", f"{child}.json")

    def aggregate_path(self, attempt_id: str) -> Path:
        self._validate_component(attempt_id, "attempt ID")
        return self._safe_path("attempts", attempt_id, "phase-result.json")

    def dispatch_path(self, attempt_id: str, child: str) -> Path:
        self._validate_component(attempt_id, "attempt ID")
        self._validate_component(child, "child")
        return self._safe_path("attempts", attempt_id, "dispatch", f"{child}.json")

    def prompt_path(self, attempt_id: str, child: str) -> Path:
        self._validate_component(attempt_id, "attempt ID")
        self._validate_component(child, "child")
        return self._safe_path("attempts", attempt_id, "prompts", f"{child}.md")

    def knowledge_path(self, attempt_id: str, child: str) -> Path:
        self._validate_component(attempt_id, "attempt ID")
        self._validate_component(child, "child")
        return self._safe_path("knowledge-packets", attempt_id, f"{child}.json")

    def write_immutable(self, path: Path, payload: bytes) -> bool:
        safe_path = self._safe_existing_path(path)
        safe_path.parent.mkdir(parents=True, exist_ok=True)
        safe_path = self._safe_existing_path(safe_path)
        temporary = self._temporary_path(safe_path)
        try:
            temporary.write_bytes(payload)
            try:
                os.link(temporary, safe_path)
            except FileExistsError:
                if safe_path.is_symlink():
                    raise AppError(
                        "invalid_storage_path", "workflow storage path must not be a symlink"
                    )
                if not safe_path.is_file() or safe_path.read_bytes() != payload:
                    raise AppError(
                        "immutable_conflict",
                        f"immutable workflow file already has different content: {safe_path}",
                    )
                return False
            return True
        finally:
            temporary.unlink(missing_ok=True)

    def create(self, state: RunState) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        state_temporary = self._temporary_path(self.state_path)
        events_temporary = self._temporary_path(self.events_path)
        try:
            state_payload = self._serialize_state(state.to_dict())
            state_temporary.write_text(state_payload, encoding="utf-8")
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
        validate_plain_value(data)
        return RunState.from_dict(data)

    def save(self, expected_version: int, state: RunState, event: Event) -> None:
        with self.event_lock():
            self.save_locked(expected_version, state, event)

    def save_locked(self, expected_version: int, state: RunState, event: Event) -> None:
        current = self.load()
        if current.version != expected_version:
            raise AppError(
                "stale_state",
                "state version changed; reload before writing",
                exit_status=4,
            )
        next_version = expected_version + 1
        state_data = state.to_dict()
        state_data["version"] = next_version
        validate_plain_value(state_data, path="state")
        state_payload = self._serialize_state(state_data)
        event_payload = self._serialize_event(next_version, event)
        self.normalize_event_tail_locked(recover_malformed=False)

        state.version = next_version
        temporary = self.state_path.with_suffix(".yaml.tmp")
        temporary.write_text(state_payload, encoding="utf-8")
        temporary.replace(self.state_path)
        self._append_event_payload_locked(event_payload)

    def append_event(self, version: int, event: Event) -> None:
        payload = self._serialize_event(version, event)
        with self.event_lock():
            self.normalize_event_tail_locked(recover_malformed=False)
            self._append_event_payload_locked(payload)

    @contextmanager
    def event_lock(self):
        self.run_dir.mkdir(parents=True, exist_ok=True)
        with self.events_lock_path.open("a+b") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def normalize_event_tail_locked(self, *, recover_malformed: bool) -> bytes:
        payload = self.events_path.read_bytes()
        if not payload or payload.endswith(b"\n"):
            return payload
        boundary = payload.rfind(b"\n") + 1
        tail = payload[boundary:]
        try:
            json.loads(tail.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as error:
            if not recover_malformed:
                raise AppError("invalid_state", "workflow event tail is malformed") from error
            payload = payload[:boundary]
        else:
            payload += b"\n"
        self.events_path.write_bytes(payload)
        return payload

    @staticmethod
    def _serialize_event(version: int, event: Event) -> str:
        event_data = {"type": event.type, "version": version, "data": event.data}
        if event.timestamp is not None:
            event_data["timestamp"] = event.timestamp
        validate_plain_value(event_data, path="event")
        return json.dumps(event_data, separators=(",", ":")) + "\n"

    def _append_event_payload_locked(self, event_payload: str) -> None:
        with self.events_path.open("a", encoding="utf-8") as stream:
            stream.write(event_payload)

    @staticmethod
    def _serialize_state(data: dict[str, object]) -> str:
        return yaml.safe_dump(data, sort_keys=False)

    @staticmethod
    def _temporary_path(path: Path) -> Path:
        return path.with_name(f".{path.name}.{uuid4().hex}.tmp")

    @staticmethod
    def _validate_component(value: str, name: str) -> None:
        if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9_-]+", value) is None:
            raise AppError(
                "invalid_storage_path", f"{name} is not a safe workflow path component"
            )

    def _safe_path(self, *parts: str) -> Path:
        return self._safe_existing_path(self.run_dir.joinpath(*parts))

    def _safe_existing_path(self, path: Path) -> Path:
        root = self.run_dir.resolve()
        try:
            relative = path.relative_to(self.run_dir)
        except ValueError as error:
            raise AppError(
                "invalid_storage_path", "workflow storage path escapes the run directory"
            ) from error
        current = self.run_dir
        if current.is_symlink():
            raise AppError(
                "invalid_storage_path", "workflow storage path must not be a symlink"
            )
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise AppError(
                    "invalid_storage_path", "workflow storage path must not be a symlink"
                )
        try:
            current.resolve().relative_to(root)
        except ValueError as error:
            raise AppError(
                "invalid_storage_path", "workflow storage path escapes the run directory"
            ) from error
        return current
