from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from tests.e2e.fake_agent import CliDriver, FakeAgent, ProjectTemplate


@dataclass(frozen=True, slots=True)
class _TemplatePaths:
    root: Path

    def language_neutral(self) -> ProjectTemplate:
        return ProjectTemplate(self.root / "examples" / "language-neutral")


@pytest.fixture()
def project_template() -> ProjectTemplate:
    repo_root = Path(__file__).resolve().parents[2]
    return _TemplatePaths(repo_root).language_neutral()


def _run_phase(
    app: CliDriver,
    agent: FakeAgent,
    run_id: str,
    phase: str,
    *,
    finding_child: str | None = None,
) -> None:
    attempt = app.workflow_begin(run_id, phase)
    for item in attempt["dispatch_plan"]:
        finding = None
        if item["child"] == finding_child:
            finding = "implementation missing retry branch"
        result_path = agent.run(Path(item["packet_file"]), finding=finding)
        app.workflow_stage(run_id, result_path)
    app.workflow_finalize(run_id, attempt["attempt_id"])


def test_complete_run_recovery_rerun_and_knowledge_growth(
    tmp_path: Path,
    project_template: ProjectTemplate,
) -> None:
    project = project_template.copy_to(tmp_path / "business-repo")
    app = CliDriver(project)
    agent = FakeAgent(project)

    run = app.workflow_init(source_revision="abc123")
    for phase in ("spec", "plan", "implement"):
        _run_phase(app, agent, run["run_id"], phase)
        app.workflow_review_transition(run["run_id"])

    _run_phase(app, agent, run["run_id"], "verify", finding_child="code_review")
    pending = app.workflow_status(run["run_id"])
    assert pending["current_phase"] == "verify"
    assert pending["status"] == "running"
    app.workflow_review_transition(
        run["run_id"],
        reruns={
            "implement.code": "add the missing retry branch and tests",
            "verify.code_review": "repeat code review after implementing the branch",
        },
    )

    recovered = app.workflow_status(run["run_id"])
    assert recovered["current_phase"] == "implement"

    _run_phase(app, agent, run["run_id"], "implement")
    app.workflow_review_transition(run["run_id"])

    _run_phase(app, agent, run["run_id"], "verify")
    app.workflow_review_transition(run["run_id"])

    candidate = app.wiki_propose(agent.propose_knowledge(run["run_id"]))
    approved = app.wiki_promote(candidate["id"], candidate["digest"], reviewer="alice")
    results = app.wiki_search(text="retry branch", repository="business-repo")

    assert approved["status"] == "approved"
    assert approved["id"] in [item["id"] for item in results]
    assert app.workflow_status(run["run_id"])["status"] == "completed"
