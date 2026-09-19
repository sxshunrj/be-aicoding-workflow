from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from ai_workflow_gui.app import create_app  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
REPO_YAML = (
    "repository: demo\n"
    "wiki_path: wiki\n"
    "max_attempts: 2\n"
    "review_mode: human\n"
    "commands:\n"
    "  build: [bash, -c, 'exit 0']\n"
    "  unit_test: [bash, -c, 'exit 0']\n"
    "  integration_test: [bash, -c, 'exit 0']\n"
)


@pytest.fixture
def client(tmp_path):
    app = create_app(
        config_path=tmp_path / "gui" / "config.json",
        home=tmp_path / "home",
    )
    return TestClient(app)


def make_repo(root: Path, name: str = "demo-repo") -> Path:
    repo = root / name
    repo.mkdir(parents=True)
    (repo / ".ai-workflow.yaml").write_text(REPO_YAML, encoding="utf-8")
    return repo


def make_wiki(root: Path) -> Path:
    wiki = root / "demo-repo" / "wiki"
    for sub in ("approved", "candidates", "archive"):
        (wiki / sub).mkdir(parents=True, exist_ok=True)
    taxonomy = REPO_ROOT / "wiki" / "taxonomy.yaml"
    (wiki / "taxonomy.yaml").write_text(
        taxonomy.read_text(encoding="utf-8"), encoding="utf-8"
    )
    return wiki


def register(client: TestClient, repo: Path) -> str:
    response = client.post("/api/repos", json={"path": str(repo)})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def write_proposal(root: Path) -> Path:
    path = root / "proposal.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "title": "Promote deterministic wiki knowledge",
                "type": "rule",
                "summary": "Approved knowledge must not depend on stale content.",
                "body": "# Claim\n\nPromotions must check the digest before approval.",
                "scope": {
                    "repos": ["demo"],
                    "services": ["workflow"],
                    "paths": [],
                    "languages": [],
                    "phases": ["implement"],
                },
                "tags": ["wiki", "lifecycle"],
                "sources": [{"kind": "run", "ref": "RUN-20260714-123456-abcdef"}],
                "reuse_reason": "The guard applies to every future review.",
                "confidence": "high",
                "possible_conflicts": [],
                "suggested_owners": ["team-wiki"],
                "review_after": "2026-10-14",
                "raw_logs": "bounded log excerpt",
            }
        ),
        encoding="utf-8",
    )
    return path
