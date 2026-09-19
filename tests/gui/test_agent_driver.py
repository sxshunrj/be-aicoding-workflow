from __future__ import annotations

import time

from fastapi.testclient import TestClient

from ai_workflow_gui.agent_runner import DEFAULT_AGENT_COMMAND

from tests.gui.conftest import make_repo, register


def _init(client: TestClient, repo_id: str) -> str:
    response = client.post(
        f"/api/repos/{repo_id}/runs",
        json={"requirement": "driver test", "source_revision": "rev"},
    )
    assert response.status_code == 201
    return response.json()["run_id"]


def test_agent_config_default_and_validation(client: TestClient):
    assert client.get("/api/agent-config").json()["command"] == DEFAULT_AGENT_COMMAND

    missing = client.put("/api/agent-config", json={"command": "claude -p"})
    assert missing.status_code == 400

    empty = client.put("/api/agent-config", json={"command": "   "})
    assert empty.status_code == 400

    ok = client.put("/api/agent-config", json={"command": "printf '%s' {prompt}"})
    assert ok.status_code == 200
    assert client.get("/api/agent-config").json()["command"] == "printf '%s' {prompt}"


def test_drive_spawns_captures_output_and_exits(client: TestClient, tmp_path):
    repo_id = register(client, make_repo(tmp_path))
    client.put("/api/agent-config", json={"command": "printf '%s' {prompt}"})
    run_id = _init(client, repo_id)

    started = client.post(f"/api/repos/{repo_id}/runs/{run_id}/drive")
    assert started.status_code == 200, started.text
    assert started.json()["active"] in (True, False)  # printf 可能瞬间退出

    deadline = time.time() + 5
    tail: list[str] = []
    while time.time() < deadline:
        status = client.get(f"/api/repos/{repo_id}/runs/{run_id}/drive").json()
        if status["exit_code"] is not None:
            tail = status["tail"]
            break
        time.sleep(0.1)
    assert status["exit_code"] == 0
    joined = "\n".join(tail)
    assert run_id in joined
    assert "resume" in joined
    assert status["active"] is False

    # 已退出任务不再可停止
    stopped = client.delete(f"/api/repos/{repo_id}/runs/{run_id}/drive")
    assert stopped.status_code == 400


def test_drive_busy_guard_and_stop(client: TestClient, tmp_path):
    repo_id = register(client, make_repo(tmp_path))
    client.put("/api/agent-config", json={"command": "bash -c 'sleep 5' {prompt}"})
    run_id = _init(client, repo_id)

    started = client.post(f"/api/repos/{repo_id}/runs/{run_id}/drive")
    assert started.status_code == 200
    assert started.json()["active"] is True

    busy = client.post(f"/api/repos/{repo_id}/runs/{run_id}/drive")
    assert busy.status_code == 409
    assert busy.json()["code"] == "driver_busy"

    stopped = client.delete(f"/api/repos/{repo_id}/runs/{run_id}/drive")
    assert stopped.status_code == 200
    assert stopped.json()["active"] in (True, False)  # SIGTERM 后瞬间可能仍在

    deadline = time.time() + 5
    while time.time() < deadline:
        status = client.get(f"/api/repos/{repo_id}/runs/{run_id}/drive").json()
        if status["exit_code"] is not None:
            break
        time.sleep(0.1)
    assert status["exit_code"] is not None and status["exit_code"] != 0

    # 终止后可重新驱动
    again = client.post(f"/api/repos/{repo_id}/runs/{run_id}/drive")
    assert again.status_code == 200
    client.delete(f"/api/repos/{repo_id}/runs/{run_id}/drive")


def test_drive_rejects_terminal_run(client: TestClient, tmp_path):
    repo_id = register(client, make_repo(tmp_path))
    run_id = _init(client, repo_id)
    aborted = client.post(f"/api/repos/{repo_id}/runs/{run_id}/abort")
    assert aborted.status_code == 200
    response = client.post(f"/api/repos/{repo_id}/runs/{run_id}/drive")
    assert response.status_code == 400
    assert "终态" in response.json()["message"]


def test_drive_rejects_unspawnable_command(client: TestClient, tmp_path):
    repo_id = register(client, make_repo(tmp_path))
    client.put(
        "/api/agent-config",
        json={"command": "/nonexistent-binary-xyz -p {prompt}"},
    )
    run_id = _init(client, repo_id)
    response = client.post(f"/api/repos/{repo_id}/runs/{run_id}/drive")
    assert response.status_code == 400
    assert response.json()["code"] == "agent_spawn_failed"
