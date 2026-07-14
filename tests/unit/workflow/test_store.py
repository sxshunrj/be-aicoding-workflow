import json
from pathlib import Path

import pytest

from ai_workflow.errors import AppError
from ai_workflow.workflow.models import RunState
from ai_workflow.workflow.store import Event, StateStore


def test_state_round_trip_and_event_append(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "run")
    state = RunState.new("RUN-001", "abc123")
    store.create(state)

    loaded = store.load()
    loaded.status = "running"
    store.save(
        expected_version=0,
        state=loaded,
        event=Event(type="run_started", data={"phase": "spec"}),
    )

    assert store.load().version == 1
    assert '"type":"run_started"' in store.events_path.read_text(encoding="utf-8")


def test_rejects_stale_state_write(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "run")
    store.create(RunState.new("RUN-001", "abc123"))
    current = store.load()
    store.save(0, current, Event(type="first", data={}))

    with pytest.raises(AppError, match="state version changed") as error:
        store.save(0, current, Event(type="stale", data={}))

    assert error.value.code == "stale_state"
    assert error.value.exit_status == 4


def test_create_initializes_empty_log_and_refuses_existing_state(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "run")
    store.create(RunState.new("RUN-001", "abc123"))

    assert store.events_path.read_text(encoding="utf-8") == ""
    with pytest.raises(AppError):
        store.create(RunState.new("RUN-002", "def456"))


def test_saved_event_is_compact_json_with_new_version(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "run")
    state = RunState.new("RUN-001", "abc123")
    store.create(state)
    store.save(0, state, Event(type="first", data={"accepted": True}))

    line = store.events_path.read_text(encoding="utf-8").strip()
    assert json.loads(line) == {
        "type": "first",
        "version": 1,
        "data": {"accepted": True},
    }
    assert ": " not in line
