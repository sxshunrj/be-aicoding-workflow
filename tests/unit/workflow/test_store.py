import json
from pathlib import Path
import threading

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


def test_invalid_event_does_not_advance_persisted_state(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "run")
    state = RunState.new("RUN-001", "abc123")
    store.create(state)

    with pytest.raises(TypeError, match="plain serialization value"):
        store.save(0, state, Event(type="invalid", data={"value": object()}))

    assert store.load().version == 0
    assert store.events_path.read_text(encoding="utf-8") == ""


def test_tuple_event_value_is_rejected_instead_of_coerced_to_json_list(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "run")
    state = RunState.new("RUN-001", "abc123")
    store.create(state)

    with pytest.raises(TypeError, match="plain serialization value"):
        store.save(0, state, Event(type="invalid", data={"value": (1, 2)}))

    assert store.load().version == 0


def test_event_lock_prevents_append_loss_during_tail_normalization(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "run")
    state = RunState.new("RUN-001", "abc123")
    store.create(state)
    store.save(0, state, Event("base", {}))
    store.events_path.write_bytes(store.events_path.read_bytes().removesuffix(b"\n"))
    started = threading.Event()

    def append_competing_event() -> None:
        started.set()
        store.append_event(1, Event("competing", {}))

    with store.event_lock():
        thread = threading.Thread(target=append_competing_event)
        thread.start()
        assert started.wait(1)
        store.normalize_event_tail_locked(recover_malformed=True)
        assert thread.is_alive()
    thread.join(2)

    events = [json.loads(line) for line in store.events_path.read_text().splitlines()]
    assert [event["type"] for event in events] == ["base", "competing"]


def test_malformed_tail_rejects_save_before_state_replacement(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "run")
    state = RunState.new("RUN-001", "abc123")
    store.create(state)
    store.events_path.write_bytes(b'{"incomplete"')

    with pytest.raises(AppError) as error:
        store.save(0, state, Event("later", {}))

    assert error.value.code == "invalid_state"
    assert store.load().version == 0
