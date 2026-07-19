import json
import os
from pathlib import Path
import threading

import pytest

from ai_workflow.errors import AppError
from ai_workflow.workflow.graph import RunGraphNode, WorkflowProfile
from ai_workflow.workflow.models import Phase, RunState
from ai_workflow.workflow.store import Event, StateStore


def new_state(run_id: str = "RUN-001", revision: str = "abc123") -> RunState:
    graph = {
        "spec.spec": RunGraphNode("spec.spec", Phase.SPEC, "spec"),
        "plan.solution": RunGraphNode("plan.solution", Phase.PLAN, "solution"),
        "implement.code": RunGraphNode("implement.code", Phase.IMPLEMENT, "code"),
        "verify.code_review": RunGraphNode(
            "verify.code_review", Phase.VERIFY, "code_review"
        ),
    }
    return RunState.new(
        run_id,
        revision,
        "Test persistence",
        WorkflowProfile.FULL,
        graph,
        Phase.SPEC,
    )


def test_state_round_trip_and_event_append(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "run")
    state = new_state()
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


def test_owned_artifact_path_is_attempt_scoped(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "run")

    assert store.owned_artifact_path("plan-1-abcdef", "prd") == (
        tmp_path / "run" / "attempts" / "plan-1-abcdef" / "artifacts" / "prd.md"
    )


def test_schema_v1_state_load_has_machine_readable_error(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "run")
    store.create(new_state())
    payload = store.state_path.read_text(encoding="utf-8")
    store.state_path.write_text(
        payload.replace("schema_version: 2", "schema_version: 1"),
        encoding="utf-8",
    )

    with pytest.raises(AppError, match="unsupported schema_version") as error:
        store.load()

    assert error.value.code == "unsupported_schema_version"


def test_rejects_stale_state_write(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "run")
    store.create(new_state())
    current = store.load()
    store.save(0, current, Event(type="first", data={}))

    with pytest.raises(AppError, match="state version changed") as error:
        store.save(0, current, Event(type="stale", data={}))

    assert error.value.code == "stale_state"
    assert error.value.exit_status == 4


def test_create_initializes_empty_log_and_refuses_existing_state(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "run")
    store.create(new_state())

    assert store.events_path.read_text(encoding="utf-8") == ""
    with pytest.raises(AppError):
        store.create(new_state("RUN-002", "def456"))


def test_saved_event_is_compact_json_with_new_version(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "run")
    state = new_state()
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
    state = new_state()
    store.create(state)

    with pytest.raises(TypeError, match="plain serialization value"):
        store.save(0, state, Event(type="invalid", data={"value": object()}))

    assert store.load().version == 0
    assert store.events_path.read_text(encoding="utf-8") == ""


def test_tuple_event_value_is_rejected_instead_of_coerced_to_json_list(
    tmp_path: Path,
) -> None:
    store = StateStore(tmp_path / "run")
    state = new_state()
    store.create(state)

    with pytest.raises(TypeError, match="plain serialization value"):
        store.save(0, state, Event(type="invalid", data={"value": (1, 2)}))

    assert store.load().version == 0


def test_event_lock_prevents_append_loss_during_tail_normalization(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "run")
    state = new_state()
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
    state = new_state()
    store.create(state)
    store.events_path.write_bytes(b'{"incomplete"')

    with pytest.raises(AppError) as error:
        store.save(0, state, Event("later", {}))

    assert error.value.code == "invalid_state"
    assert store.load().version == 0


def test_immutable_write_holds_parent_fd_across_symlink_swap(
    tmp_path: Path, monkeypatch
) -> None:
    store = StateStore(tmp_path / "run")
    store.create(new_state())
    target = store.run_dir / "nested" / "child.json"
    outside = tmp_path / "outside"
    outside.mkdir()
    parked = store.run_dir / "nested-parked"
    payload = b'{"safe":true}\n'
    real_link = os.link
    swapped = False

    def swap_parent_before_link(source, destination, *args, **kwargs):
        nonlocal swapped
        if not swapped:
            swapped = True
            target.parent.rename(parked)
            target.parent.symlink_to(outside, target_is_directory=True)
            if kwargs.get("src_dir_fd") is None:
                (outside / Path(source).name).write_bytes(payload)
        return real_link(source, destination, *args, **kwargs)

    monkeypatch.setattr(os, "link", swap_parent_before_link)

    with pytest.raises(AppError, match="accessed safely"):
        store.write_immutable(target, payload)

    assert swapped
    assert not (outside / target.name).exists()
    assert not (parked / target.name).exists()


def test_identical_immutable_write_rejects_parent_swap_without_removing_target(
    tmp_path: Path, monkeypatch
) -> None:
    store = StateStore(tmp_path / "run")
    store.create(new_state())
    target = store.run_dir / "nested" / "child.json"
    target.parent.mkdir()
    payload = b'{"safe":true}\n'
    target.write_bytes(payload)
    outside = tmp_path / "outside"
    outside.mkdir()
    parked = store.run_dir / "nested-parked"
    real_link = os.link

    def swap_parent_before_link(source, destination, *args, **kwargs):
        target.parent.rename(parked)
        target.parent.symlink_to(outside, target_is_directory=True)
        return real_link(source, destination, *args, **kwargs)

    monkeypatch.setattr(os, "link", swap_parent_before_link)

    with pytest.raises(AppError, match="accessed safely"):
        store.write_immutable(target, payload)

    assert not (outside / target.name).exists()
    assert (parked / target.name).read_bytes() == payload
    assert list(parked.glob(".*.tmp")) == []


def test_immutable_write_rejects_run_root_replacement_and_cleans_new_target(
    tmp_path: Path, monkeypatch
) -> None:
    store = StateStore(tmp_path / "run")
    store.create(new_state())
    target = store.run_dir / "nested" / "child.json"
    payload = b'{"safe":true}\n'
    outside = tmp_path / "outside"
    outside.mkdir()
    parked_run = tmp_path / "run-parked"
    real_link = os.link

    def swap_run_root_before_link(source, destination, *args, **kwargs):
        store.run_dir.rename(parked_run)
        store.run_dir.symlink_to(outside, target_is_directory=True)
        return real_link(source, destination, *args, **kwargs)

    monkeypatch.setattr(os, "link", swap_run_root_before_link)

    with pytest.raises(AppError, match="accessed safely"):
        store.write_immutable(target, payload)

    assert not (outside / "nested" / target.name).exists()
    assert not (parked_run / "nested" / target.name).exists()
    assert list((parked_run / "nested").glob(".*.tmp")) == []
