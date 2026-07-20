from pathlib import Path

from ai_workflow.workflow.graph import NodeValidity
from tests.e2e.fake_agent import CliDriver, FakeAgent, ProjectTemplate


def _run_full_to_verify(app: CliDriver, agent: FakeAgent, run_id: str) -> dict[str, object]:
    for phase in ("spec", "plan"):
        attempt = app.workflow_begin(run_id, phase)
        for item in attempt["dispatch_plan"]:
            app.workflow_stage(run_id, agent.run(Path(item["packet_file"])))
        app.workflow_finalize(run_id, attempt["attempt_id"])
        app.workflow_review_transition(run_id)
    implement = app.workflow_begin(run_id, "implement")
    app.workflow_stage(run_id, agent.run(Path(implement["dispatch_plan"][0]["packet_file"])))
    app.workflow_finalize(run_id, implement["attempt_id"])
    return app.workflow_review_transition(run_id)


def test_checkpoint_survives_new_process_and_anchors_verification(
    tmp_path: Path, project_template: ProjectTemplate
) -> None:
    project = project_template.copy_to(tmp_path / "checkpoint-repo")
    app = CliDriver(project)
    agent = FakeAgent(project)
    run = app.workflow_init(profile="full")
    state = _run_full_to_verify(app, agent, run["run_id"])
    checkpoint = state["artifacts"]["checkpoints"]["active"]

    recovered = CliDriver(project)
    verify = recovered.workflow_begin(run["run_id"], "verify")
    packet = recovered.load_packet(verify["dispatch_plan"][0])

    assert recovered.workflow_status(run["run_id"])["current_phase"] == "verify"
    assert packet.source_revision == checkpoint["commit_sha"]
    assert recovered.git_rev_parse(checkpoint["hidden_ref"]) == checkpoint["commit_sha"]


def test_implementation_rerun_creates_new_checkpoint_and_invalidates_all_verify(
    tmp_path: Path, project_template: ProjectTemplate
) -> None:
    project = project_template.copy_to(tmp_path / "rerun-repo")
    app = CliDriver(project)
    agent = FakeAgent(project)
    run = app.workflow_init(profile="full")
    state = _run_full_to_verify(app, agent, run["run_id"])
    first = state["artifacts"]["checkpoints"]["active"]

    verify = app.workflow_begin(run["run_id"], "verify")
    for item in verify["dispatch_plan"]:
        app.workflow_stage(run["run_id"], agent.run(Path(item["packet_file"])))
    app.workflow_finalize(run["run_id"], verify["attempt_id"])
    state = app.workflow_review_transition(
        run["run_id"], reruns={"implement.code": "fix implementation"}
    )
    assert state["current_phase"] == "implement"
    implement = app.workflow_begin(run["run_id"], "implement")
    app.workflow_stage(run["run_id"], agent.run(Path(implement["dispatch_plan"][0]["packet_file"])))
    app.workflow_finalize(run["run_id"], implement["attempt_id"])
    state = app.workflow_review_transition(run["run_id"])
    second = state["artifacts"]["checkpoints"]["active"]

    assert second["parent_commit"] == first["commit_sha"]
    assert state["artifacts"]["checkpoints"]["previous"]["commit_sha"] == first["commit_sha"]
    assert state["run_graph"]["verify.code_review"]["validity"] == NodeValidity.PENDING.value


def test_verify_child_rerun_reuses_checkpoint_and_valid_siblings(
    tmp_path: Path, project_template: ProjectTemplate
) -> None:
    project = project_template.copy_to(tmp_path / "verify-rerun-repo")
    app = CliDriver(project)
    agent = FakeAgent(project)
    run = app.workflow_init(profile="full")
    state = _run_full_to_verify(app, agent, run["run_id"])
    checkpoint = state["artifacts"]["checkpoints"]["active"]
    verify = app.workflow_begin(run["run_id"], "verify")
    for item in verify["dispatch_plan"]:
        app.workflow_stage(run["run_id"], agent.run(Path(item["packet_file"])))
    app.workflow_finalize(run["run_id"], verify["attempt_id"])

    state = app.workflow_review_transition(
        run["run_id"], reruns={"verify.code_review": "repeat focused review"}
    )
    assert state["current_phase"] == "verify"
    assert state["artifacts"]["checkpoints"]["active"]["commit_sha"] == checkpoint["commit_sha"]
    rerun = app.workflow_begin(run["run_id"], "verify")
    actions = {item["child"]: item["action"] for item in rerun["dispatch_plan"]}
    assert actions["code_review"] == "rerun"


def test_dirty_overlap_blocks_without_moving_head_branch_or_index(
    tmp_path: Path, project_template: ProjectTemplate
) -> None:
    project = project_template.copy_to(tmp_path / "dirty-overlap-repo")
    app = CliDriver(project)
    agent = FakeAgent(project)
    run = app.workflow_init(profile="full")
    for phase in ("spec", "plan"):
        attempt = app.workflow_begin(run["run_id"], phase)
        for item in attempt["dispatch_plan"]:
            app.workflow_stage(run["run_id"], agent.run(Path(item["packet_file"])))
        app.workflow_finalize(run["run_id"], attempt["attempt_id"])
        app.workflow_review_transition(run["run_id"])

    (project / "src" / "app.py").write_text("preexisting dirty\n", encoding="utf-8")
    before = app.snapshot_git_state()
    implement = app.workflow_begin(run["run_id"], "implement")
    app.workflow_stage(run["run_id"], agent.run(Path(implement["dispatch_plan"][0]["packet_file"])))
    app.workflow_finalize(run["run_id"], implement["attempt_id"])
    decision = app.workflow_review(run["run_id"])

    status, payload = app.workflow_review_accept_status(run["run_id"], decision["digest"])

    assert status != 0
    assert payload["error"]["code"] == "checkpoint_scope_ambiguous"
    blocked = app.workflow_status(run["run_id"])
    assert blocked["status"] == "blocked"
    assert blocked["artifacts"]["_checkpoint_failure"]["code"] == "checkpoint_scope_ambiguous"
    assert app.snapshot_git_state() == before
