from datetime import datetime
import hashlib
import json
from pathlib import Path

import pytest
import yaml

from ai_workflow.contracts.artifacts import ArtifactRef, ChildResult
from ai_workflow.contracts.packets import DispatchPacket
from ai_workflow.errors import AppError
from ai_workflow.workflow.models import Phase
from ai_workflow.workflow.service import UNABLE_REASON, WorkflowService
from ai_workflow.workflow.store import Event, StateStore


def _config(repo: Path, *, review_mode: str = "human") -> None:
    repo.mkdir(parents=True, exist_ok=True)
    (repo / ".ai-workflow.yaml").write_text(
        f"repository: demo\nreview_mode: {review_mode}\n",
        encoding="utf-8",
    )


def _skill_dir(repo: Path) -> Path:
    contracts = repo / "skill" / "references" / "agents"
    contracts.mkdir(parents=True, exist_ok=True)
    for name in (
        "common-phase-contract.md",
        "spec-writer.md",
        "planner.md",
        "coder.md",
        "test-runner.md",
        "code-reviewer.md",
    ):
        (contracts / name).write_text(f"# {name}\n", encoding="utf-8")
    return contracts.parents[1]


def _set_phase(service: WorkflowService, run_id: str, phase: Phase) -> None:
    store = service._store(run_id)
    state = service.status(run_id)
    state.current_phase = phase.value
    store.save(state.version, state, Event("test_phase_selected", {"phase": phase.value}))


def _finalize(
    service: WorkflowService,
    repo: Path,
    run_id: str,
    phase: Phase = Phase.SPEC,
    *,
    unable_child: str | None = None,
) -> None:
    if service.status(run_id).current_phase != phase.value:
        _set_phase(service, run_id, phase)
    attempt = service.begin(run_id, phase, _skill_dir(repo))
    for item in attempt.dispatch_plan:
        assert item.packet_file is not None
        packet = DispatchPacket.load(item.packet_file)
        unable = item.child == unable_child
        artifact = None
        if not unable:
            artifact_path = repo / packet.allowed_output_path
            artifact_path.parent.mkdir(parents=True, exist_ok=True)
            artifact_path.write_text(f"# {item.node}\n", encoding="utf-8")
            artifact = ArtifactRef(
                packet.allowed_output_path,
                hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
                2,
                phase,
                item.child,
                "abc123",
            )
        result_path = repo / f"{attempt.attempt_id}-{item.child}.json"
        ChildResult(
            run_id,
            phase,
            item.child,
            attempt.attempt_id,
            packet.execution_mode,
            "unable_to_complete" if unable else "completed",
            "child result",
            artifact,
            (),
        ).write(result_path)
        service.stage(run_id, attempt.attempt_id, item.child, result_path)
    service.finalize(run_id, attempt.attempt_id)


def _new_finalized(
    repo: Path,
    *,
    review_mode: str = "human",
    phase: Phase = Phase.SPEC,
    unable_child: str | None = None,
) -> tuple[WorkflowService, str]:
    _config(repo, review_mode=review_mode)
    service = WorkflowService(
        repo,
        clock=lambda: datetime(2026, 7, 15, 12, 0, 0),
        id_factory=lambda: "abcdef",
    )
    state = service.init(repo, "abc123", "Test review gates")
    _finalize(service, repo, state.run_id, phase, unable_child=unable_child)
    return service, state.run_id


def _canonical_digest(decision) -> str:
    unsigned = {
        "decision": decision.decision,
        "run_id": decision.run_id,
        "phase": decision.phase,
        "state_version": decision.state_version,
        "proposed_reruns": decision.proposed_reruns,
        "effective_reruns": decision.effective_reruns,
    }
    payload = json.dumps(
        unsigned, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def test_human_review_is_deterministic_persisted_and_idempotent(
    tmp_path: Path,
) -> None:
    service, run_id = _new_finalized(tmp_path)
    before = service.status(run_id).version

    first = service.review(run_id, {})
    persisted = service.status(run_id)
    second = WorkflowService(tmp_path).review(run_id, {})

    assert first.decision == "human_review"
    assert first.run_id == run_id
    assert first.phase == "spec"
    assert first.state_version == before + 1
    assert first.proposed_reruns == ()
    assert first.effective_reruns == ()
    assert first.digest == _canonical_digest(first)
    assert persisted.version == first.state_version
    assert persisted.artifacts["review_gate"]["digest"] == first.digest
    assert second == first
    assert service.status(run_id).version == first.state_version


def test_human_review_requires_exact_persisted_acceptance_and_consumes_once(
    tmp_path: Path,
) -> None:
    service, run_id = _new_finalized(tmp_path)
    decision = service.review(run_id, {})

    with pytest.raises(AppError, match="review gate") as missing:
        service.transition(run_id)
    assert missing.value.code == "review_gate_required"

    with pytest.raises(AppError, match="digest") as mismatch:
        service.record_review_acceptance(run_id, "0" * 64)
    assert mismatch.value.code == "review_gate_mismatch"

    accepted = service.record_review_acceptance(run_id, decision.digest)
    accepted_version = service.status(run_id).version
    repeated = WorkflowService(tmp_path).record_review_acceptance(
        run_id, decision.digest
    )

    assert accepted == decision
    assert repeated == decision
    assert service.status(run_id).version == accepted_version

    transitioned = WorkflowService(tmp_path).transition(run_id)
    assert transitioned.current_phase == "plan"
    assert "review_gate" not in transitioned.artifacts

    with pytest.raises(AppError, match="finalized|review gate"):
        service.transition(run_id)


def test_auto_accept_is_limited_to_non_verify_phases(tmp_path: Path) -> None:
    service, run_id = _new_finalized(tmp_path, review_mode="auto_accept")

    decision = service.review(run_id, {})
    assert decision.decision == "accept"
    assert WorkflowService(tmp_path).transition(run_id).current_phase == "plan"

    verify_service, verify_run = _new_finalized(
        tmp_path / "verify",
        review_mode="auto_accept",
        phase=Phase.VERIFY,
    )
    verify_decision = verify_service.review(verify_run, {})
    assert verify_decision.decision == "human_review"
    with pytest.raises(AppError, match="review gate"):
        verify_service.transition(verify_run)


@pytest.mark.parametrize(
    ("initial_mode", "changed_mode", "expected_decision"),
    [
        ("human", "auto_accept", "human_review"),
        ("auto_accept", "human", "accept"),
    ],
)
def test_run_review_policy_is_immutable_after_disk_config_changes(
    tmp_path: Path,
    initial_mode: str,
    changed_mode: str,
    expected_decision: str,
) -> None:
    service, run_id = _new_finalized(tmp_path, review_mode=initial_mode)
    _config(tmp_path, review_mode=changed_mode)

    decision = service.review(run_id, {})

    assert decision.decision == expected_decision
    if decision.decision == "human_review":
        with pytest.raises(AppError, match="review gate"):
            service.transition(run_id)
        service.record_review_acceptance(run_id, decision.digest)
    assert service.transition(run_id).current_phase == "plan"


def test_transition_does_not_reread_live_review_config(
    tmp_path: Path, monkeypatch
) -> None:
    service, run_id = _new_finalized(tmp_path, review_mode="auto_accept")
    decision = service.review(run_id, {})
    assert decision.decision == "accept"

    def fail_live_config_read(_repo):
        raise AssertionError("transition must use immutable run policy")

    monkeypatch.setattr(
        "ai_workflow.config.RepositoryConfig.load", fail_live_config_read
    )

    assert service.transition(run_id).current_phase == "plan"


def test_status_rejects_state_only_run_policy_tampering(tmp_path: Path) -> None:
    service, run_id = _new_finalized(tmp_path)
    state_path = service._store(run_id).state_path
    data = yaml.safe_load(state_path.read_text(encoding="utf-8"))
    data["artifacts"]["_run_policy"]["review_mode"] = "auto_accept"
    state_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    with pytest.raises(AppError, match="run policy") as error:
        service.status(run_id)
    assert error.value.code == "invalid_state"


def test_status_rejects_run_policy_replay_from_another_run(tmp_path: Path) -> None:
    first_repo = tmp_path / "first"
    second_repo = tmp_path / "second"
    first, first_run = _new_finalized(first_repo, review_mode="human")
    second, second_run = _new_finalized(second_repo, review_mode="auto_accept")
    first_path = first._store(first_run).state_path
    second_path = second._store(second_run).state_path
    first_data = yaml.safe_load(first_path.read_text(encoding="utf-8"))
    second_data = yaml.safe_load(second_path.read_text(encoding="utf-8"))
    first_data["artifacts"]["_run_policy"] = second_data["artifacts"][
        "_run_policy"
    ]
    first_path.write_text(
        yaml.safe_dump(first_data, sort_keys=False), encoding="utf-8"
    )

    with pytest.raises(AppError, match="run policy") as error:
        first.status(first_run)
    assert error.value.code == "invalid_state"


def test_status_rejects_run_policy_evidence_tampering(tmp_path: Path) -> None:
    service, run_id = _new_finalized(tmp_path)
    state = service.status(run_id)
    evidence_path = Path(state.artifacts["_run_policy"]["evidence_path"])
    evidence_path.write_text('{"review_mode":"auto_accept"}\n', encoding="utf-8")

    with pytest.raises(AppError, match="run policy") as error:
        service.status(run_id)
    assert error.value.code == "invalid_state"


def test_init_policy_write_failure_does_not_publish_state_or_events(
    tmp_path: Path, monkeypatch
) -> None:
    _config(tmp_path)
    service = WorkflowService(
        tmp_path,
        clock=lambda: datetime(2026, 7, 15, 12, 0, 0),
        id_factory=lambda: "abcdef",
    )
    store = service._store("RUN-20260715-120000-abcdef")

    def fail_policy_write(_store, _path, _payload):
        raise OSError("injected policy write failure")

    monkeypatch.setattr(StateStore, "write_immutable", fail_policy_write)

    with pytest.raises(OSError, match="policy write failure"):
        service.init(tmp_path, "abc123", "Policy write must precede state")

    assert not store.state_path.exists()
    assert not store.events_path.exists()


def test_init_policy_is_visible_before_state_can_be_loaded(
    tmp_path: Path, monkeypatch
) -> None:
    _config(tmp_path)
    service = WorkflowService(
        tmp_path,
        clock=lambda: datetime(2026, 7, 15, 12, 0, 0),
        id_factory=lambda: "abcdef",
    )
    store = service._store("RUN-20260715-120000-abcdef")
    real_write = StateStore.write_immutable
    observed = False

    def observe_policy_barrier(policy_store, path, payload):
        nonlocal observed
        observed = True
        with pytest.raises(FileNotFoundError):
            policy_store.load()
        assert not policy_store.events_path.exists()
        created = real_write(policy_store, path, payload)
        assert path.read_bytes() == payload
        with pytest.raises(FileNotFoundError):
            policy_store.load()
        return created

    monkeypatch.setattr(StateStore, "write_immutable", observe_policy_barrier)

    state = service.init(tmp_path, "abc123", "Observe policy publication barrier")

    assert observed
    assert service.status(state.run_id).run_id == state.run_id
    assert store.events_path.read_text(encoding="utf-8") == ""


def test_init_reuses_identical_orphan_policy_after_state_create_failure(
    tmp_path: Path, monkeypatch
) -> None:
    _config(tmp_path)
    service = WorkflowService(
        tmp_path,
        clock=lambda: datetime(2026, 7, 15, 12, 0, 0),
        id_factory=lambda: "abcdef",
    )
    run_id = "RUN-20260715-120000-abcdef"
    store = service._store(run_id)
    real_create = StateStore.create
    create_calls = 0

    def fail_first_create(state_store, state):
        nonlocal create_calls
        create_calls += 1
        if create_calls == 1:
            raise OSError("injected state create failure")
        return real_create(state_store, state)

    monkeypatch.setattr(StateStore, "create", fail_first_create)

    with pytest.raises(OSError, match="state create failure"):
        service.init(tmp_path, "abc123", "Retry identical policy")

    expected_policy = service._run_policy_payload(
        run_id, "abc123", "full", "human"
    )
    assert store.policy_path().read_bytes() == expected_policy
    assert not store.state_path.exists()
    assert not store.events_path.exists()

    recovered = service.init(tmp_path, "abc123", "Retry identical policy")

    assert service.status(recovered.run_id).run_id == run_id
    with pytest.raises(AppError) as error:
        service.init(tmp_path, "abc123", "Retry identical policy")
    assert error.value.code == "state_exists"


def test_init_conflicting_orphan_policy_does_not_publish_state(
    tmp_path: Path,
) -> None:
    _config(tmp_path, review_mode="human")
    service = WorkflowService(
        tmp_path,
        clock=lambda: datetime(2026, 7, 15, 12, 0, 0),
        id_factory=lambda: "abcdef",
    )
    run_id = "RUN-20260715-120000-abcdef"
    store = service._store(run_id)
    conflicting = service._run_policy_payload(
        run_id, "abc123", "full", "auto_accept"
    )
    store.run_dir.mkdir(parents=True)
    store.write_immutable(store.policy_path(), conflicting)

    with pytest.raises(AppError) as error:
        service.init(tmp_path, "abc123", "Reject conflicting orphan policy")

    assert error.value.code == "immutable_conflict"
    assert store.policy_path().read_bytes() == conflicting
    assert not store.state_path.exists()
    assert not store.events_path.exists()


def test_init_preserves_state_exists_for_valid_existing_run(
    tmp_path: Path,
) -> None:
    _config(tmp_path, review_mode="human")
    service = WorkflowService(
        tmp_path,
        clock=lambda: datetime(2026, 7, 15, 12, 0, 0),
        id_factory=lambda: "abcdef",
    )
    existing = service.init(tmp_path, "abc123", "Existing run wins")
    _config(tmp_path, review_mode="auto_accept")

    with pytest.raises(AppError) as error:
        service.init(tmp_path, "abc123", "Conflicting retry")

    assert error.value.code == "state_exists"
    assert service.status(existing.run_id).requirement == "Existing run wins"


@pytest.mark.parametrize(
    ("reruns", "message"),
    [
        ({"unknown.node": "retry"}, "unknown rerun node"),
        ({"spec.spec": "  "}, "reason must not be empty"),
        ({"plan.solution": "not reached"}, "forward phase"),
        ({"spec.spec": UNABLE_REASON}, "actionable"),
    ],
)
def test_review_rejects_invalid_node_rerun_proposals(
    tmp_path: Path, reruns: dict[str, str], message: str
) -> None:
    service, run_id = _new_finalized(tmp_path)

    with pytest.raises(AppError, match=message):
        service.review(run_id, reruns)


def test_review_requires_replacing_unable_placeholder_with_actionable_reason(
    tmp_path: Path,
) -> None:
    service, run_id = _new_finalized(tmp_path, unable_child="spec")

    with pytest.raises(AppError, match="actionable"):
        service.review(run_id, {})

    decision = service.review(run_id, {"spec.spec": "clarify acceptance criteria"})
    assert decision.proposed_reruns == (
        ("spec.spec", "clarify acceptance criteria"),
    )
    assert decision.effective_reruns == decision.proposed_reruns


def test_review_acceptance_rejects_stale_proposal_version(tmp_path: Path) -> None:
    service, run_id = _new_finalized(tmp_path)
    decision = service.review(run_id, {})
    store = service._store(run_id)
    state = service.status(run_id)
    store.save(state.version, state, Event("unrelated_state_change", {}))

    with pytest.raises(AppError, match="stale") as error:
        service.record_review_acceptance(run_id, decision.digest)
    assert error.value.code == "stale_review_gate"


def test_transition_rejects_stale_accepted_gate(tmp_path: Path) -> None:
    service, run_id = _new_finalized(tmp_path)
    decision = service.review(run_id, {})
    service.record_review_acceptance(run_id, decision.digest)
    store = service._store(run_id)
    state = service.status(run_id)
    store.save(state.version, state, Event("unrelated_state_change", {}))

    with pytest.raises(AppError, match="stale") as error:
        service.transition(run_id)
    assert error.value.code == "stale_review_gate"


def test_status_rejects_corrupted_review_gate_digest(tmp_path: Path) -> None:
    service, run_id = _new_finalized(tmp_path)
    service.review(run_id, {})
    state_path = service._store(run_id).state_path
    data = yaml.safe_load(state_path.read_text(encoding="utf-8"))
    data["artifacts"]["review_gate"]["digest"] = "f" * 64
    state_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    with pytest.raises(AppError, match="review gate") as error:
        service.status(run_id)
    assert error.value.code == "invalid_state"


def test_review_defers_preserved_forward_rerun_until_its_phase(tmp_path: Path) -> None:
    service, run_id = _new_finalized(tmp_path, phase=Phase.VERIFY)
    first = service.review(
        run_id,
        {
            "implement.code": "add the missing branch",
            "verify.code_review": "repeat review after the implementation rerun",
        },
    )
    service.record_review_acceptance(run_id, first.digest)
    assert service.transition(run_id).current_phase == "implement"
    _finalize(service, tmp_path, run_id, Phase.IMPLEMENT)

    decision = service.review(run_id, {})

    assert decision.effective_reruns == ()
    assert (
        service.status(run_id).run_graph["verify.code_review"].reason
        == "repeat review after the implementation rerun"
    )


def test_review_retry_repairs_missing_proposal_event_once(
    tmp_path: Path, monkeypatch
) -> None:
    service, run_id = _new_finalized(tmp_path)
    store = service._store(run_id)
    real_open = Path.open
    failed = False

    def fail_event_append(path, mode="r", *args, **kwargs):
        nonlocal failed
        if path == store.events_path and mode == "a" and not failed:
            failed = True
            raise OSError("injected review proposal event failure")
        return real_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_event_append)
    with pytest.raises(OSError, match="proposal event failure"):
        service.review(run_id, {})

    recovered = WorkflowService(tmp_path).review(run_id, {})
    stable = WorkflowService(tmp_path).review(run_id, {})
    events = [
        json.loads(line) for line in store.events_path.read_text().splitlines()
    ]

    assert recovered == stable
    assert sum(
        event["type"] == "review_proposed"
        and event["data"]["digest"] == recovered.digest
        for event in events
    ) == 1


def test_review_accept_retry_repairs_missing_acceptance_event_once(
    tmp_path: Path, monkeypatch
) -> None:
    service, run_id = _new_finalized(tmp_path)
    decision = service.review(run_id, {})
    store = service._store(run_id)
    real_open = Path.open
    failed = False

    def fail_event_append(path, mode="r", *args, **kwargs):
        nonlocal failed
        if path == store.events_path and mode == "a" and not failed:
            failed = True
            raise OSError("injected review acceptance event failure")
        return real_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_event_append)
    with pytest.raises(OSError, match="acceptance event failure"):
        service.record_review_acceptance(run_id, decision.digest)

    recovered = WorkflowService(tmp_path).record_review_acceptance(
        run_id, decision.digest
    )
    stable = WorkflowService(tmp_path).record_review_acceptance(
        run_id, decision.digest
    )
    events = [
        json.loads(line) for line in store.events_path.read_text().splitlines()
    ]

    assert recovered == stable == decision
    assert sum(
        event["type"] == "review_accepted"
        and event["data"]["digest"] == decision.digest
        for event in events
    ) == 1


def test_repeated_review_rejects_duplicate_acceptance_event(tmp_path: Path) -> None:
    service, run_id = _new_finalized(tmp_path)
    decision = service.review(run_id, {})
    service.record_review_acceptance(run_id, decision.digest)
    store = service._store(run_id)
    events = [
        json.loads(line) for line in store.events_path.read_text().splitlines()
    ]
    original = next(event for event in events if event["type"] == "review_accepted")
    store.append_event(
        service.status(run_id).version,
        Event("review_accepted", original["data"], original["timestamp"]),
    )

    with pytest.raises(AppError, match="review acceptance event evidence"):
        service.review(run_id, {})


@pytest.mark.parametrize("kind", ["duplicate", "conflicting"])
def test_review_rejects_duplicate_or_conflicting_proposal_event(
    tmp_path: Path, kind: str
) -> None:
    service, run_id = _new_finalized(tmp_path)
    decision = service.review(run_id, {})
    store = service._store(run_id)
    events = [
        json.loads(line) for line in store.events_path.read_text().splitlines()
    ]
    original = next(event for event in events if event["type"] == "review_proposed")
    duplicate = json.loads(json.dumps(original["data"]))
    if kind == "conflicting":
        duplicate["accepted_at"] = "2026-07-15T13:00:00"
    store.append_event(
        service.status(run_id).version,
        Event("review_proposed", duplicate, original["timestamp"]),
    )

    with pytest.raises(AppError, match="review proposal event evidence") as error:
        service.review(run_id, {})
    assert error.value.code == "invalid_state"
    assert service.status(run_id).artifacts["review_gate"]["digest"] == (
        decision.digest
    )


def test_transition_retry_repairs_missing_transition_event_once(
    tmp_path: Path, monkeypatch
) -> None:
    service, run_id = _new_finalized(tmp_path)
    decision = service.review(run_id, {})
    service.record_review_acceptance(run_id, decision.digest)
    store = service._store(run_id)
    real_open = Path.open
    failed = False

    def fail_event_append(path, mode="r", *args, **kwargs):
        nonlocal failed
        if path == store.events_path and mode == "a" and not failed:
            failed = True
            raise OSError("injected transition event failure")
        return real_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_event_append)
    with pytest.raises(OSError, match="transition event failure"):
        service.transition(run_id)

    recovered = WorkflowService(tmp_path).transition(run_id)
    events = [
        json.loads(line) for line in store.events_path.read_text().splitlines()
    ]

    assert recovered.current_phase == "plan"
    assert "review_gate" not in recovered.artifacts
    assert sum(
        event["type"] == "workflow_transitioned"
        and event["data"]["digest"] == decision.digest
        for event in events
    ) == 1
    with pytest.raises(AppError, match="finalized|review gate"):
        WorkflowService(tmp_path).transition(run_id)


def test_begin_next_phase_repairs_missing_transition_event_first(
    tmp_path: Path, monkeypatch
) -> None:
    service, run_id = _new_finalized(tmp_path)
    decision = service.review(run_id, {})
    service.record_review_acceptance(run_id, decision.digest)
    store = service._store(run_id)
    real_open = Path.open
    failed = False

    def fail_event_append(path, mode="r", *args, **kwargs):
        nonlocal failed
        if path == store.events_path and mode == "a" and not failed:
            failed = True
            raise OSError("injected transition event failure")
        return real_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_event_append)
    with pytest.raises(OSError, match="transition event failure"):
        service.transition(run_id)

    attempt = WorkflowService(tmp_path).begin(
        run_id, Phase.PLAN, _skill_dir(tmp_path)
    )
    events = [
        json.loads(line) for line in store.events_path.read_text().splitlines()
    ]

    assert attempt.phase == "plan"
    assert [event["type"] for event in events[-2:]] == [
        "workflow_transitioned",
        "phase_begun",
    ]


@pytest.mark.parametrize("kind", ["duplicate", "conflicting"])
def test_transition_rejects_duplicate_or_conflicting_event(
    tmp_path: Path, kind: str
) -> None:
    service, run_id = _new_finalized(tmp_path)
    decision = service.review(run_id, {})
    service.record_review_acceptance(run_id, decision.digest)
    service.transition(run_id)
    store = service._store(run_id)
    events = [
        json.loads(line) for line in store.events_path.read_text().splitlines()
    ]
    original = next(
        event for event in events if event["type"] == "workflow_transitioned"
    )
    duplicate = json.loads(json.dumps(original["data"]))
    if kind == "conflicting":
        duplicate["result_phase"] = "verify"
    store.append_event(
        service.status(run_id).version,
        Event("workflow_transitioned", duplicate, original["timestamp"]),
    )

    with pytest.raises(AppError, match="transition event evidence") as error:
        service.transition(run_id)
    assert error.value.code == "invalid_state"


@pytest.mark.parametrize("operation", ["block", "abort"])
def test_gate_invalidating_lifecycle_change_rejects_duplicate_review_evidence(
    tmp_path: Path, operation: str
) -> None:
    service, run_id = _new_finalized(tmp_path)
    service.review(run_id, {})
    store = service._store(run_id)
    events = [
        json.loads(line) for line in store.events_path.read_text().splitlines()
    ]
    original = next(event for event in events if event["type"] == "review_proposed")
    store.append_event(
        service.status(run_id).version,
        Event("review_proposed", original["data"], original["timestamp"]),
    )

    with pytest.raises(AppError, match="review proposal event evidence") as error:
        if operation == "block":
            service.block(run_id, "wait for user")
        else:
            service.abort(run_id)
    assert error.value.code == "invalid_state"
