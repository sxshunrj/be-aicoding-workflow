from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from tests.gui.conftest import REPO_ROOT, make_repo, register

SKILLS_SOURCE = str(REPO_ROOT / "skills")


def test_install_then_doctor_green(client: TestClient, tmp_path):
    register(client, make_repo(tmp_path))

    installed = client.post(
        "/api/install",
        json={
            "client": "codex",
            "scope": "user",
            "mode": "copy",
            "source_root": SKILLS_SOURCE,
        },
    )
    assert installed.status_code == 200, installed.text
    report = installed.json()
    assert report["ok"] is True
    assert report["data"]["items"], "expected at least one installed skill"
    statuses = {item["status"] for item in report["data"]["items"]}
    assert statuses <= {"installed", "updated", "skipped"}

    doctor = client.get(
        "/api/doctor",
        params={"client": "codex", "source_root": SKILLS_SOURCE},
    )
    assert doctor.status_code == 200
    body = doctor.json()
    assert body["ok"] is True, body
    assert body["data"]["failed"] == []


def test_doctor_rejects_missing_source_root(client: TestClient, tmp_path):
    response = client.get(
        "/api/doctor", params={"source_root": "/nonexistent/skills"}
    )
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_arguments"


def test_install_validates_arguments(client: TestClient):
    response = client.post(
        "/api/install",
        json={"client": "codex", "scope": "user", "mode": "bogus"},
    )
    assert response.status_code == 400

    repo_scope = client.post(
        "/api/install",
        json={"client": "codex", "scope": "repo", "mode": "copy"},
    )
    assert repo_scope.status_code == 400
    assert repo_scope.json()["code"] == "invalid_arguments"
