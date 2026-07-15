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


def _complete_remaining_phases(app: CliDriver, agent: FakeAgent, run_id: str) -> None:
    for phase in ("verify",):
        packet = app.workflow_begin(run_id, phase)
        result_path = agent.run(Path(packet["packet_path"]))
        app.workflow_submit(run_id, result_path)


def test_complete_run_recovery_rerun_and_knowledge_growth(
    tmp_path: Path,
    project_template: ProjectTemplate,
) -> None:
    project = project_template.copy_to(tmp_path / "business-repo")
    app = CliDriver(project)
    agent = FakeAgent(project)

    run = app.workflow_init(source_revision="abc123")
    for phase in ("spec", "plan", "implement"):
        packet = app.workflow_begin(run["run_id"], phase)
        app.workflow_submit(run["run_id"], agent.run(Path(packet["packet_path"])))

    verify_packet = app.workflow_begin(run["run_id"], "verify")
    finding_result = agent.run(
        Path(verify_packet["packet_path"]),
        finding="implementation missing retry branch",
    )
    assert finding_result.exists()
    app.workflow_transition(
        run["run_id"],
        reruns={"implement": "add the missing retry branch and tests"},
    )

    recovered = app.workflow_status(run["run_id"])
    assert recovered["current_phase"] == "implement"

    packet = app.workflow_begin(run["run_id"], "implement")
    app.workflow_submit(run["run_id"], agent.run(Path(packet["packet_path"])))

    _complete_remaining_phases(app, agent, run["run_id"])

    candidate = app.wiki_propose(agent.propose_knowledge(run["run_id"]))
    approved = app.wiki_promote(candidate["id"], candidate["digest"], reviewer="alice")
    results = app.wiki_search(text="retry branch", repository="business-repo")

    assert approved["status"] == "approved"
    assert approved["id"] in [item["id"] for item in results]
    assert app.workflow_status(run["run_id"])["status"] == "completed"
