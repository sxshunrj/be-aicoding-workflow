from pathlib import Path

from tests.e2e.fake_agent import CliDriver, FakeAgent, ProjectTemplate


def test_grill_run_stages_owned_prd_and_completes_plan_implement_verify(
    tmp_path: Path, project_template: ProjectTemplate
) -> None:
    project = project_template.copy_to(tmp_path / "grill-repo")
    app = CliDriver(project)
    agent = FakeAgent(project)

    run = app.workflow_init(profile="grill")
    assert run["current_phase"] == "plan"
    plan = app.workflow_begin(run["run_id"], "plan")
    assert plan["dispatch_plan"][0]["node"] == "plan.prd"
    assert plan["dispatch_plan"][0]["execution_kind"] == "workflow_owned"
    prd = project / "tmp-prd.md"
    prd.write_text(
        "# PRD\n\n## Issue Identifier\nISSUE-001\n\n"
        "## Tracer-Bullet Vertical Slice\nUpdate src/app.py.\n\n"
        "## Acceptance Criteria\n- verify passes\n",
        encoding="utf-8",
    )
    app.workflow_stage_owned(
        run["run_id"],
        plan["attempt_id"],
        "plan",
        "prd",
        prd,
        "PRD completed",
    )
    app.workflow_finalize(run["run_id"], plan["attempt_id"])
    state = app.workflow_review_transition(run["run_id"])
    assert state["current_phase"] == "implement"

    implement = app.workflow_begin(run["run_id"], "implement")
    app.workflow_stage(run["run_id"], agent.run(Path(implement["dispatch_plan"][0]["packet_file"])))
    app.workflow_finalize(run["run_id"], implement["attempt_id"])
    state = app.workflow_review_transition(run["run_id"])
    checkpoint = state["artifacts"]["checkpoints"]["active"]
    assert checkpoint["hidden_ref"]
    assert app.git_rev_parse(checkpoint["hidden_ref"]) == checkpoint["commit_sha"]

    verify = app.workflow_begin(run["run_id"], "verify")
    for item in verify["dispatch_plan"]:
        packet = app.load_packet(item)
        assert packet.source_revision == checkpoint["commit_sha"]
        app.workflow_stage(run["run_id"], agent.run(Path(item["packet_file"])))
    app.workflow_finalize(run["run_id"], verify["attempt_id"])
    state = app.workflow_review_transition(run["run_id"])

    assert state["status"] == "completed"
    assert "spec.spec" not in state["run_graph"]
