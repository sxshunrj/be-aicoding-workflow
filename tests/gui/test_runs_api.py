from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from tests.gui.conftest import make_repo, register


def init_run(client: TestClient, repo_id: str, requirement: str = "demo requirement") -> dict:
    response = client.post(
        f"/api/repos/{repo_id}/runs",
        json={"requirement": requirement, "source_revision": "rev-0001"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_init_status_list_flow(client: TestClient, tmp_path):
    repo_id = register(client, make_repo(tmp_path))
    run = init_run(client, repo_id)

    assert run["run_id"].startswith("RUN-")
    assert run["status"] == "pending"
    assert run["current_phase"] == "spec"
    assert len(run["run_graph"]) == 8  # full profile: 8 nodes (verify 节点随 commands 存在)

    listing = client.get(f"/api/repos/{repo_id}/runs").json()
    assert [item["run_id"] for item in listing["runs"]] == [run["run_id"]]
    assert listing["errors"] == []

    status = client.get(f"/api/repos/{repo_id}/runs/{run['run_id']}").json()
    assert status["requirement"] == "demo requirement"


def test_init_requires_source_revision_without_git(client: TestClient, tmp_path):
    repo_id = register(client, make_repo(tmp_path))
    response = client.post(
        f"/api/repos/{repo_id}/runs", json={"requirement": "demo"}
    )
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_source_revision"


def test_init_rejects_bad_profile(client: TestClient, tmp_path):
    repo_id = register(client, make_repo(tmp_path))
    response = client.post(
        f"/api/repos/{repo_id}/runs",
        json={
            "requirement": "demo",
            "source_revision": "rev",
            "profile": "bogus",
        },
    )
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_profile"


def test_list_runs_isolated_from_corrupt_state(client: TestClient, tmp_path):
    repo = make_repo(tmp_path)
    repo_id = register(client, repo)
    good = init_run(client, repo_id)

    runs_dir = repo / ".ai-workflow" / "runs"
    broken = runs_dir / "RUN-20990101-000000-broken1"
    broken.mkdir()
    (broken / "state.yaml").write_text("{ not yaml at all", encoding="utf-8")

    listing = client.get(f"/api/repos/{repo_id}/runs").json()
    assert [item["run_id"] for item in listing["runs"]] == [good["run_id"]]
    assert listing["errors"][0]["run_id"] == "RUN-20990101-000000-broken1"


def test_status_missing_run_is_404(client: TestClient, tmp_path):
    repo_id = register(client, make_repo(tmp_path))
    response = client.get(f"/api/repos/{repo_id}/runs/RUN-20990101-000000-abcdef")
    assert response.status_code == 404
    assert response.json()["code"] == "state_not_found"


def test_events_empty_then_rejects_bad_run_id(client: TestClient, tmp_path):
    repo_id = register(client, make_repo(tmp_path))
    run = init_run(client, repo_id)
    events = client.get(f"/api/repos/{repo_id}/runs/{run['run_id']}/events")
    assert events.status_code == 200
    assert events.json() == {"events": []}

    bad = client.get(f"/api/repos/{repo_id}/runs/not-a-run-id/events")
    assert bad.status_code == 404
    assert bad.json()["code"] == "invalid_run_id"


def test_review_accept_without_gate_rejected(client: TestClient, tmp_path):
    repo_id = register(client, make_repo(tmp_path))
    run = init_run(client, repo_id)
    response = client.post(
        f"/api/repos/{repo_id}/runs/{run['run_id']}/review-accept",
        json={"expected_digest": "0" * 64},
    )
    # fresh run 阶段未 finalize，先撞 invalid_transition(400)；
    # gate 缺失本身映射 409（status_for 单测覆盖）
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_transition"


def test_block_and_abort_flow(client: TestClient, tmp_path):
    repo_id = register(client, make_repo(tmp_path))

    first = init_run(client, repo_id, requirement="blocked run")
    empty_reason = client.post(
        f"/api/repos/{repo_id}/runs/{first['run_id']}/block", json={"reason": "  "}
    )
    assert empty_reason.status_code == 400
    blocked = client.post(
        f"/api/repos/{repo_id}/runs/{first['run_id']}/block",
        json={"reason": "waiting for human input"},
    )
    assert blocked.status_code == 200
    assert blocked.json()["status"] == "blocked"

    second = init_run(client, repo_id, requirement="aborted run")
    aborted = client.post(f"/api/repos/{repo_id}/runs/{second['run_id']}/abort")
    assert aborted.status_code == 200
    assert aborted.json()["status"] == "aborted"

    listing = client.get(f"/api/repos/{repo_id}/runs").json()
    by_id = {item["run_id"]: item["status"] for item in listing["runs"]}
    assert by_id[first["run_id"]] == "blocked"
    assert by_id[second["run_id"]] == "aborted"


def test_resume_validates_rerun_reasons(client: TestClient, tmp_path):
    repo_id = register(client, make_repo(tmp_path))
    run = init_run(client, repo_id)
    blocked = client.post(
        f"/api/repos/{repo_id}/runs/{run['run_id']}/block",
        json={"reason": "hold"},
    )
    assert blocked.status_code == 200
    empty_reason = client.post(
        f"/api/repos/{repo_id}/runs/{run['run_id']}/resume",
        json={"reruns": {"implement.code": "   "}},
    )
    assert empty_reason.status_code == 400
    assert empty_reason.json()["code"] == "invalid_arguments"


def test_run_files_listing_read_and_traversal_guard(client: TestClient, tmp_path):
    repo_id = register(client, make_repo(tmp_path))
    run = init_run(client, repo_id)

    listing = client.get(f"/api/repos/{repo_id}/runs/{run['run_id']}/files")
    assert listing.status_code == 200
    paths = [item["path"] for item in listing.json()["files"]]
    assert "state.yaml" in paths
    assert "run-policy.json" in paths

    state = client.get(
        f"/api/repos/{repo_id}/runs/{run['run_id']}/file",
        params={"path": "state.yaml"},
    )
    assert state.status_code == 200
    assert "run_id" in state.json()["content"]

    escape = client.get(
        f"/api/repos/{repo_id}/runs/{run['run_id']}/file",
        params={"path": "../../../.ai-workflow.yaml"},
    )
    assert escape.status_code == 400

    missing = client.get(
        f"/api/repos/{repo_id}/runs/{run['run_id']}/file",
        params={"path": "nope.json"},
    )
    assert missing.status_code == 404

    bad_run = client.get("/api/repos/%s/runs/RUN-20990101-000000-abcdef/files" % repo_id)
    assert bad_run.status_code == 404
