from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from ai_workflow.errors import AppError
from ai_workflow.wiki.models import KnowledgeEntry
from ai_workflow.wiki.repository import WikiRepository
from ai_workflow.wiki.service import WikiService


def _wiki(root: Path) -> WikiRepository:
    for name in ("approved", "candidates", "archive"):
        (root / name).mkdir()
    (root / "taxonomy.yaml").write_text(
        "schema_version: 1\n"
        "types: [rule, decision, pattern, pitfall, procedure]\n"
        "phases: [implement]\n",
        encoding="utf-8",
    )
    return WikiRepository(root)


def _entry(
    entry_id: str,
    *,
    status: str,
    title: str,
    tags: list[str] | None = None,
    supersedes: list[str] | None = None,
    conflicts: list[str] | None = None,
) -> KnowledgeEntry:
    return KnowledgeEntry.from_parts(
        {
            "id": entry_id,
            "title": title,
            "type": "rule",
            "status": status,
            "summary": "Use deterministic verification commands before handoff.",
            "scope": {
                "repos": ["demo"],
                "services": ["workflow"],
                "paths": [],
                "languages": [],
                "phases": ["implement"],
            },
            "tags": tags or ["verification"],
            "owners": ["team-wiki"],
            "reviewers": ["alice"] if status == "approved" else [],
            "created_at": date(2026, 7, 14),
            "reviewed_at": date(2026, 7, 15) if status == "approved" else None,
            "review_after": date(2026, 10, 14),
            "sources": [{"kind": "run", "ref": "RUN-20260714-123456-abcdef"}],
            "supersedes": supersedes or [],
            "conflicts_with": conflicts or [],
        },
        f"# {title}\n\nRun repository verification before handoff.",
    )


def _seed_review_wiki(root: Path) -> tuple[WikiRepository, Path]:
    repository = _wiki(root)
    existing = _entry(
        "KW-rule-existing-001",
        status="approved",
        title="Run repository verification before handoff",
    )
    conflict = _entry(
        "KW-rule-conflict-001",
        status="approved",
        title="Avoid stale verification commands",
        tags=["verification", "conflict"],
    )
    old = _entry(
        "KW-rule-old-001",
        status="approved",
        title="Old verification command checklist",
    )
    for entry in (existing, conflict, old):
        (root / "approved" / f"{entry.id}.md").write_text(
            repository.serialize(entry),
            encoding="utf-8",
        )
    candidate = _entry(
        "KW-rule-deterministic-001",
        status="candidate",
        title="Use deterministic verification commands",
        tags=["verification"],
        supersedes=["KW-rule-old-001"],
        conflicts=["KW-rule-conflict-001"],
    )
    candidate_path = repository.write_candidate(candidate)
    return repository, candidate_path


def test_review_candidate_returns_digest_related_approved_and_declared_links(
    tmp_path: Path,
) -> None:
    repository, candidate_path = _seed_review_wiki(tmp_path)
    service = WikiService(repository)

    review = service.review_candidate("KW-rule-deterministic-001")

    assert review["candidate"]["digest"] == repository.path_digest(candidate_path)
    assert review["candidate"]["status"] == "candidate"
    assert review["candidate"]["id"] == "KW-rule-deterministic-001"
    assert review["related_approved"][0]["id"] == "KW-rule-existing-001"
    assert review["related_approved"][0]["digest"] == repository.path_digest(
        tmp_path / "approved" / "KW-rule-existing-001.md"
    )
    assert review["declared_conflicts"] == ["KW-rule-conflict-001"]
    assert review["declared_supersedes"] == ["KW-rule-old-001"]


def test_review_candidate_rejects_non_candidate_ids(tmp_path: Path) -> None:
    _seed_review_wiki(tmp_path)
    service = WikiService(WikiRepository(tmp_path))

    with pytest.raises(AppError, match="candidate"):
        service.review_candidate("KW-rule-existing-001")


def test_review_candidate_bounds_related_results(tmp_path: Path) -> None:
    _seed_review_wiki(tmp_path)
    service = WikiService(WikiRepository(tmp_path))

    review = service.review_candidate("KW-rule-deterministic-001", max_related=1)

    assert len(review["related_approved"]) == 1


def test_review_candidate_scores_scope_title_and_tags(tmp_path: Path) -> None:
    repository, _ = _seed_review_wiki(tmp_path)
    unrelated = _entry(
        "KW-rule-unrelated-001",
        status="approved",
        title="Unrelated deployment note",
        tags=["deploy"],
    )
    (tmp_path / "approved" / f"{unrelated.id}.md").write_text(
        repository.serialize(unrelated),
        encoding="utf-8",
    )
    service = WikiService(repository)

    review = service.review_candidate("KW-rule-deterministic-001")

    ids = [item["id"] for item in review["related_approved"]]
    assert ids.index("KW-rule-existing-001") < ids.index("KW-rule-unrelated-001")
    assert "repository:demo" in review["related_approved"][0]["match_reasons"]
    assert any(
        reason.startswith("tag:") or reason.startswith("title:")
        for reason in review["related_approved"][0]["match_reasons"]
    )
