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
