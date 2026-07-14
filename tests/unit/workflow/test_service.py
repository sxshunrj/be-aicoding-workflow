from datetime import datetime
from pathlib import Path

import pytest

from ai_workflow.errors import AppError
from ai_workflow.workflow.models import Phase
from ai_workflow.workflow.service import WorkflowService


def _config(repo: Path, max_attempts: int = 3) -> None:
    (repo / ".ai-workflow.yaml").write_text(
        f"repository: demo\nmax_attempts: {max_attempts}\n", encoding="utf-8"
    )


def test_init_uses_injected_clock_and_id_factory(tmp_path: Path) -> None:
    _config(tmp_path)
    service = WorkflowService(
        clock=lambda: datetime(2026, 7, 14, 12, 34, 56),
        id_factory=lambda: "a1b2c3",
    )

    state = service.init(tmp_path, "abc123")

    assert state.run_id == "RUN-20260714-123456-a1b2c3"


def test_begin_rejects_attempt_over_repository_limit(tmp_path: Path) -> None:
    _config(tmp_path, max_attempts=1)
    service = WorkflowService(tmp_path, id_factory=lambda: "a1b2c3")
    state = service.init(tmp_path, "abc123")
    service.begin(state.run_id, Phase.SPEC)
    service.transition(state.run_id, False, {Phase.SPEC: "try again"})

    with pytest.raises(AppError, match="maximum attempts"):
        service.begin(state.run_id, Phase.SPEC)


@pytest.mark.parametrize("suffix", ["abc12", "ABCDEF", "gggggg", "abcdef0", "../bad"])
def test_init_rejects_invalid_id_suffix(tmp_path: Path, suffix: str) -> None:
    _config(tmp_path)
    service = WorkflowService(tmp_path, id_factory=lambda: suffix)

    with pytest.raises(AppError, match="ID suffix"):
        service.init(tmp_path, "abc123")


@pytest.mark.parametrize("run_id", ["../outside", "/tmp/outside", "RUN-001"])
def test_rejects_invalid_run_id_before_resolving_store(tmp_path: Path, run_id: str) -> None:
    _config(tmp_path)

    with pytest.raises(AppError, match="run ID"):
        WorkflowService(tmp_path).status(run_id)


@pytest.mark.parametrize(
    ("begin_first", "expected"), [(False, "pending"), (True, "running")]
)
def test_resume_restores_prior_lifecycle_state(
    tmp_path: Path, begin_first: bool, expected: str
) -> None:
    _config(tmp_path)
    service = WorkflowService(tmp_path, id_factory=lambda: "abcdef")
    state = service.init(tmp_path, "abc123")
    if begin_first:
        service.begin(state.run_id, Phase.SPEC)

    service.block(state.run_id, "waiting")
    resumed = service.resume(state.run_id)

    assert resumed.status == expected
    assert resumed.nodes["spec"].status == expected


def test_verify_can_rerun_implement_then_return_to_verify(tmp_path: Path) -> None:
    _config(tmp_path)
    service = WorkflowService(tmp_path, id_factory=lambda: "abcdef")
    state = service.init(tmp_path, "abc123")
    for phase in (Phase.SPEC, Phase.PLAN, Phase.IMPLEMENT):
        service.begin(state.run_id, phase)
        state = service.transition(state.run_id, True, {})
    service.begin(state.run_id, Phase.VERIFY)

    state = service.transition(
        state.run_id, False, {Phase.IMPLEMENT: "missing branch"}
    )
    assert state.nodes["verify"].status == "pending"
    service.begin(state.run_id, Phase.IMPLEMENT)
    state = service.transition(state.run_id, True, {})
    attempt = service.begin(state.run_id, Phase.VERIFY)

    assert attempt.number == 2


def test_rerun_transition_requires_a_started_attempt(tmp_path: Path) -> None:
    _config(tmp_path)
    service = WorkflowService(tmp_path, id_factory=lambda: "abcdef")
    state = service.init(tmp_path, "abc123")

    with pytest.raises(AppError, match="current node is not running"):
        service.transition(state.run_id, False, {Phase.SPEC: "retry"})
