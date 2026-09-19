from __future__ import annotations

import subprocess

from fastapi.testclient import TestClient

from ai_workflow_gui.app import status_for

from tests.gui.conftest import make_repo, register


def test_register_list_remove_roundtrip(client: TestClient, tmp_path):
    repo = make_repo(tmp_path)
    repo_id = register(client, repo)

    listing = client.get("/api/repos").json()
    assert listing["repos"][0]["id"] == repo_id
    assert listing["repos"][0]["name"] == "demo-repo"
    assert listing["reviewer"] == ""

    response = client.delete(f"/api/repos/{repo_id}")
    assert response.status_code == 200
    assert client.get("/api/repos").json()["repos"] == []


def test_register_rejects_repo_without_config(client: TestClient, tmp_path):
    bare = tmp_path / "bare"
    bare.mkdir()
    response = client.post("/api/repos", json={"path": str(bare)})
    assert response.status_code == 404
    assert response.json()["code"] == "config_not_found"


def test_register_is_idempotent(client: TestClient, tmp_path):
    repo = make_repo(tmp_path)
    repo_id = register(client, repo)
    again = client.post("/api/repos", json={"path": str(repo)})
    assert again.status_code == 201
    assert again.json()["id"] == repo_id
    assert len(client.get("/api/repos").json()["repos"]) == 1


def test_unknown_repo_is_404(client: TestClient):
    response = client.get("/api/repos/00000000")
    assert response.status_code == 404
    assert response.json()["code"] == "repo_not_found"


def test_repo_detail_returns_config_data(client: TestClient, tmp_path):
    repo = make_repo(tmp_path)
    repo_id = register(client, repo)
    data = client.get(f"/api/repos/{repo_id}").json()
    assert data["repo"]["path"] == str(repo)
    assert data["config"]["repository"] == "demo"
    assert data["config"]["review_mode"] == "human"
    assert data["config"]["max_attempts"] == 2


def test_repo_head_without_git_is_null(client: TestClient, tmp_path):
    repo = make_repo(tmp_path)
    repo_id = register(client, repo)
    assert client.get(f"/api/repos/{repo_id}/head").json() == {"head": None}


def test_repo_head_with_git(client: TestClient, tmp_path):
    repo = make_repo(tmp_path)
    subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "--allow-empty", "-m", "init", "-q"],
        check=True,
        capture_output=True,
        env={
            "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
            "HOME": str(tmp_path),
        },
    )
    repo_id = register(client, repo)
    head = client.get(f"/api/repos/{repo_id}/head").json()["head"]
    assert head and len(head) == 40


def test_settings_reviewer_roundtrip(client: TestClient, tmp_path):
    assert client.get("/api/repos").json()["reviewer"] == ""
    response = client.put("/api/settings", json={"reviewer": "  sxshunrj "})
    assert response.status_code == 200
    assert response.json()["reviewer"] == "sxshunrj"
    assert client.get("/api/repos").json()["reviewer"] == "sxshunrj"
    rejected = client.put("/api/settings", json={"reviewer": "   "})
    assert rejected.status_code == 400


def test_status_for_mapping():
    assert status_for("state_not_found") == 404
    assert status_for("repo_not_found") == 404
    assert status_for("config_not_found") == 404
    assert status_for("invalid_run_id") == 404
    assert status_for("state_exists") == 409
    assert status_for("stale_state") == 409
    assert status_for("review_gate_required") == 409
    assert status_for("wiki_conflict") == 409
    assert status_for("invalid_profile") == 400
    assert status_for("repository_required") == 400
    assert status_for("something_unmapped") == 500


def test_git_status_endpoint(client: TestClient, tmp_path):
    repo = make_repo(tmp_path)
    subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
    env = {
        "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
        "HOME": str(tmp_path),
    }
    subprocess.run(
        ["git", "-C", str(repo), "commit", "--allow-empty", "-m", "init", "-q"],
        check=True, capture_output=True, env=env,
    )
    (repo / "tracked.txt").write_text("hello", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True, env=env)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "add file", "-q"], check=True, capture_output=True, env=env)
    # commit 后再修改 → 是真正的 tracked 变更（-uno 只列 tracked）
    (repo / "tracked.txt").write_text("hello world", encoding="utf-8")
    repo_id = register(client, repo)

    data = client.get(f"/api/repos/{repo_id}/git-status").json()
    assert "tracked.txt" in data["status"]
    assert isinstance(data["stat"], str)


def test_meta_and_client_errors(client: TestClient):
    meta = client.get("/api/meta")
    assert meta.status_code == 200
    body = meta.json()
    assert body["version"]
    assert body["python"]

    reported = client.post(
        "/api/client-errors",
        json={"message": "render failed", "context": "RunDetail", "stack": "at x"},
    )
    assert reported.status_code == 204


def test_git_diff_endpoint(client: TestClient, tmp_path):
    import subprocess

    repo = make_repo(tmp_path)
    subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
    env = {
        "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
        "HOME": str(tmp_path),
    }
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True, env=env)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "init", "-q"], check=True, capture_output=True, env=env)
    (repo / ".ai-workflow.yaml").write_text("repository: demo2\n", encoding="utf-8")
    repo_id = register(client, repo)
    data = client.get(f"/api/repos/{repo_id}/git-diff").json()
    assert "+repository: demo2" in data["diff"]
