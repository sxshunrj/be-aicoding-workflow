from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from ai_workflow.wiki.repository import WikiRepository
from ai_workflow.wiki.service import WikiService

from tests.gui.conftest import make_repo, make_wiki, register, write_proposal


def seed_candidate(tmp_path: Path) -> str:
    wiki = make_wiki(tmp_path)
    service = WikiService(WikiRepository(wiki, validate_layout=False))
    entry = service.propose(write_proposal(tmp_path))
    return entry.id


def test_candidate_listing_and_review(client: TestClient, tmp_path):
    repo = make_repo(tmp_path)
    repo_id = register(client, repo)
    entry_id = seed_candidate(tmp_path)

    listing = client.get(f"/api/repos/{repo_id}/wiki/candidates").json()
    assert len(listing["candidates"]) == 1
    candidate = listing["candidates"][0]
    assert candidate["id"] == entry_id
    assert candidate["status"] == "candidate"
    assert len(candidate["digest"]) == 64

    review = client.get(f"/api/repos/{repo_id}/wiki/candidates/{entry_id}")
    assert review.status_code == 200
    body = review.json()
    assert body["candidate"]["id"] == entry_id
    assert body["candidate"]["status"] == "candidate"
    assert "related_approved" in body


def test_promote_requires_configured_reviewer(client: TestClient, tmp_path):
    repo = make_repo(tmp_path)
    repo_id = register(client, repo)
    entry_id = seed_candidate(tmp_path)
    listing = client.get(f"/api/repos/{repo_id}/wiki/candidates").json()
    digest = listing["candidates"][0]["digest"]

    response = client.post(
        f"/api/repos/{repo_id}/wiki/candidates/{entry_id}/promote",
        json={"expected_digest": digest},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_arguments"


def test_promote_digest_guard_and_success(client: TestClient, tmp_path):
    repo = make_repo(tmp_path)
    repo_id = register(client, repo)
    entry_id = seed_candidate(tmp_path)
    client.put("/api/settings", json={"reviewer": "sxshunrj"})

    stale = client.post(
        f"/api/repos/{repo_id}/wiki/candidates/{entry_id}/promote",
        json={"expected_digest": "0" * 64},
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "wiki_conflict"

    digest = client.get(f"/api/repos/{repo_id}/wiki/candidates").json()[
        "candidates"
    ][0]["digest"]
    promoted = client.post(
        f"/api/repos/{repo_id}/wiki/candidates/{entry_id}/promote",
        json={"expected_digest": digest},
    )
    assert promoted.status_code == 200, promoted.text
    assert promoted.json()["status"] == "approved"

    remaining = client.get(f"/api/repos/{repo_id}/wiki/candidates").json()
    assert remaining["candidates"] == []


def test_reject_requires_reason_and_archives(client: TestClient, tmp_path):
    repo = make_repo(tmp_path)
    repo_id = register(client, repo)
    entry_id = seed_candidate(tmp_path)
    client.put("/api/settings", json={"reviewer": "sxshunrj"})
    digest = client.get(f"/api/repos/{repo_id}/wiki/candidates").json()[
        "candidates"
    ][0]["digest"]

    empty = client.post(
        f"/api/repos/{repo_id}/wiki/candidates/{entry_id}/reject",
        json={"reason": "  ", "expected_digest": digest},
    )
    assert empty.status_code == 400

    rejected = client.post(
        f"/api/repos/{repo_id}/wiki/candidates/{entry_id}/reject",
        json={"reason": "not reusable", "expected_digest": digest},
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "archived"
    assert client.get(f"/api/repos/{repo_id}/wiki/candidates").json()[
        "candidates"
    ] == []


def test_review_unknown_candidate_is_404(client: TestClient, tmp_path):
    repo = make_repo(tmp_path)
    repo_id = register(client, repo)
    make_wiki(tmp_path)
    response = client.get(f"/api/repos/{repo_id}/wiki/candidates/KB-none")
    assert response.status_code == 404
    assert response.json()["code"] == "wiki_not_found"


def test_approved_browsing_after_promote(client: TestClient, tmp_path):
    repo = make_repo(tmp_path)
    repo_id = register(client, repo)
    entry_id = seed_candidate(tmp_path)
    client.put("/api/settings", json={"reviewer": "sxshunrj"})
    digest = client.get(f"/api/repos/{repo_id}/wiki/candidates").json()[
        "candidates"
    ][0]["digest"]
    promoted = client.post(
        f"/api/repos/{repo_id}/wiki/candidates/{entry_id}/promote",
        json={"expected_digest": digest},
    )
    assert promoted.status_code == 200

    listing = client.get(f"/api/repos/{repo_id}/wiki/approved").json()
    assert [item["id"] for item in listing["approved"]] == [entry_id]
    assert listing["approved"][0]["reviewed_at"] is not None

    detail = client.get(f"/api/repos/{repo_id}/wiki/approved/{entry_id}")
    assert detail.status_code == 200
    body = detail.json()
    assert "Promotions must check the digest" in body["body"]

    missing = client.get(f"/api/repos/{repo_id}/wiki/approved/KB-none")
    assert missing.status_code == 404
