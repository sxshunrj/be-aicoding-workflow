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
    assert status["state"] == "exited"
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

def test_restart_adopts_running_agent(client: TestClient, tmp_path):
    from ai_workflow_gui.agent_runner import AgentDriver

    home = tmp_path / "home"
    repo_id = register(client, make_repo(tmp_path))
    client.put("/api/agent-config", json={"command": "bash -c 'sleep 30' {prompt}"})
    run_id = _init(client, repo_id)

    started = client.post(f"/api/repos/{repo_id}/runs/{run_id}/drive")
    assert started.status_code == 200

    log_dir = home / ".ai-workflow-gui" / "agent-logs"
    driver2 = AgentDriver(log_dir=log_dir)
    status = driver2.status(run_id)
    assert status["state"] == "running"
    assert status["adopted"] is True

    stopped = driver2.stop(run_id)
    assert stopped["active"] in (True, False)
    deadline = time.time() + 5
    while time.time() < deadline:
        status = driver2.status(run_id)
        if status["state"] != "running":
            break
        time.sleep(0.1)
    assert status["state"] == "unknown"  # 收养进程无退出码
    assert driver2.is_active(run_id) is False


def test_auto_resume_paths(client: TestClient, tmp_path):
    from ai_workflow.workflow.service import WorkflowService

    home = tmp_path / "home"
    repo = make_repo(tmp_path)
    repo_id = register(client, repo)
    run_id = _init(client, repo_id)
    driver = client.app.state.driver

    state = WorkflowService(repo).status(run_id)
    result = driver.auto_resume(
        run_id=run_id,
        repo_id=repo_id,
        repo_root=repo,
        state=state,
        template="bash -c 'sleep 30' {prompt}",
    )
    assert result == {"resumed": True}

    # 已在运行 → 跳过
    state = WorkflowService(repo).status(run_id)
    again = driver.auto_resume(
        run_id=run_id,
        repo_id=repo_id,
        repo_root=repo,
        state=state,
        template="bash -c 'sleep 30' {prompt}",
    )
    assert again["resumed"] is False and again["reason"] == "already_running"

    stopped = driver.stop(run_id)
    assert stopped is not None
    deadline = time.time() + 5
    while time.time() < deadline:
        if driver.status(run_id)["state"] == "exited":
            break
        time.sleep(0.1)

    # pending gate → 拒绝接力
    state = WorkflowService(repo).status(run_id)
    state.artifacts["review_gate"] = {
        "decision": "human_review",
        "accepted_at": None,
        "digest": "d" * 64,
        "phase": "verify",
        "state_version": 2,
        "proposed_reruns": [],
        "effective_reruns": [],
    }
    gated = driver.auto_resume(
        run_id=run_id,
        repo_id=repo_id,
        repo_root=repo,
        state=state,
        template="printf '%s' {prompt}",
    )
    assert gated["resumed"] is False and gated["reason"] == "gate_pending"

    # 终态 → 跳过
    state.status = "aborted"
    terminal = driver.auto_resume(
        run_id=run_id,
        repo_id=repo_id,
        repo_root=repo,
        state=state,
        template="printf '%s' {prompt}",
    )
    assert terminal["resumed"] is False and terminal["reason"] == "terminal"
    assert (home / ".ai-workflow-gui" / "agent-logs").is_dir()


def test_schedule_resume_after_agent_exit(client: TestClient, tmp_path):
    """复现真实时序缺陷：gate 接受时 agent 尚未退出 → 后台等退出后自动接力。"""
    import threading

    from ai_workflow.workflow.service import WorkflowService

    repo = make_repo(tmp_path)
    repo_id = register(client, repo)
    run_id = _init(client, repo_id)
    driver = client.app.state.driver

    first = driver.start(
        run_id=run_id,
        repo_id=repo_id,
        repo_root=repo,
        template="bash -c 'sleep 2' {prompt}",
        prompt="p",
    )
    assert first["state"] == "running"

    immediate = driver.auto_resume(
        run_id=run_id,
        repo_id=repo_id,
        repo_root=repo,
        state=WorkflowService(repo).status(run_id),
        template="printf 'second' {prompt}",
    )
    assert immediate["resumed"] is False and immediate["reason"] == "already_running"

    outcome: dict = {}
    done = threading.Event()

    def on_result(result: dict) -> None:
        outcome.update(result)
        done.set()

    driver.schedule_resume(
        run_id=run_id,
        repo_id=repo_id,
        repo_root=repo,
        template="printf %s {prompt}",
        get_state=lambda: WorkflowService(repo).status(run_id),
        timeout=10,
        interval=0.3,
        on_result=on_result,
    )
    assert done.wait(12), "auto-resume watcher did not finish"
    assert outcome["resumed"] is True

    deadline = time.time() + 5
    while time.time() < deadline:
        status = driver.status(run_id)
        if status["state"] == "exited":
            break
        time.sleep(0.1)
    assert status["state"] == "exited"
    assert status["exit_code"] == 0
    tail_text = "\n".join(status["tail"])
    assert run_id in tail_text


def test_render_argv_model_handling():
    from ai_workflow_gui.agent_runner import render_argv

    template = "claude -p {prompt} --model {model} --flag"
    assert render_argv(template, "P", "deepseek-chat") == [
        "claude", "-p", "P", "--model", "deepseek-chat", "--flag",
    ]
    assert render_argv(template, "P", "") == ["claude", "-p", "P", "--flag"]
    assert render_argv("claude --model={model} -p {prompt}", "P", "") == ["claude", "-p", "P"]
    assert render_argv("claude --model={model} -p {prompt}", "P", "m") == ["claude", "--model=m", "-p", "P"]


def test_init_run_persists_model_and_drive_uses_it(client: TestClient, tmp_path):
    from pathlib import Path as _P

    from ai_workflow_gui.config_store import load_config

    repo_id = register(client, make_repo(tmp_path))
    created = client.post(
        f"/api/repos/{repo_id}/runs",
        json={
            "requirement": "model pick",
            "source_revision": "rev",
            "model": "deepseek-chat",
        },
    )
    assert created.status_code == 201
    run_id = created.json()["run_id"]

    config = load_config(_P(client.app.state.config_path))
    assert config.run_models == {run_id: "deepseek-chat"}

    client.put(
        "/api/agent-config",
        json={"command": "bash -c 'printf %s \"$2\"' x {prompt} {model}"},
    )
    started = client.post(f"/api/repos/{repo_id}/runs/{run_id}/drive")
    assert started.status_code == 200
    deadline = time.time() + 5
    status = started.json()
    while time.time() < deadline:
        status = client.get(f"/api/repos/{repo_id}/runs/{run_id}/drive").json()
        if status["exit_code"] is not None:
            break
        time.sleep(0.1)
    assert status["exit_code"] == 0
    assert "deepseek-chat" in "\n".join(status["tail"])
