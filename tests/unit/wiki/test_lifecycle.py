from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace
import hashlib
import json

import pytest

from ai_workflow.errors import AppError
from ai_workflow.wiki.models import CandidateProposal, KnowledgeEntry, KnowledgeScope, KnowledgeStatus, KnowledgeType
from ai_workflow.wiki.repository import WikiRepository
from ai_workflow.wiki.service import WikiService


def wiki(tmp_path: Path) -> WikiRepository:
    for name in ("approved", "candidates", "archive"):
        (tmp_path / name).mkdir()
    (tmp_path / "taxonomy.yaml").write_text(
        "schema_version: 1\n"
        "types: [rule, decision, pattern, pitfall, procedure]\n"
        "phases: [implement]\n",
        encoding="utf-8",
    )
    return WikiRepository(tmp_path)


def proposal_payload(**overrides) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": 1,
        "title": "Promote deterministic wiki knowledge",
        "type": "rule",
        "summary": "Approved knowledge should not depend on stale candidate content.",
        "body": "# Claim\n\nPromotions must check the current digest before approval.",
        "scope": {
            "repos": ["demo"],
            "services": ["workflow"],
            "paths": [],
            "languages": [],
            "phases": ["implement"],
        },
        "tags": ["wiki", "lifecycle"],
        "sources": [{"kind": "run", "ref": "RUN-20260714-123456-abcdef"}],
        "reuse_reason": "The guard applies to every future review of the same entry.",
        "confidence": "high",
        "possible_conflicts": [],
        "suggested_owners": ["team-wiki"],
        "review_after": "2026-10-14",
        "raw_logs": "bounded log excerpt",
    }
    payload.update(overrides)
    return payload


def write_proposal(tmp_path: Path, **overrides) -> Path:
    path = tmp_path / "proposal.json"
    path.write_text(json.dumps(proposal_payload(**overrides)), encoding="utf-8")
    return path


def entry() -> KnowledgeEntry:
    return KnowledgeEntry.from_parts(
        {
            "id": "KW-rule-deterministic-001",
            "title": "Promote deterministic wiki knowledge",
            "type": "rule",
            "status": "candidate",
            "summary": "Approved knowledge should not depend on stale candidate content.",
            "scope": {
                "repos": ["demo"],
                "services": ["workflow"],
                "paths": [],
                "languages": [],
                "phases": ["implement"],
            },
            "tags": ["wiki", "lifecycle"],
            "owners": ["team-wiki"],
            "reviewers": [],
            "created_at": date(2026, 7, 14),
            "reviewed_at": None,
            "review_after": date(2026, 10, 14),
            "sources": [{"kind": "run", "ref": "RUN-20260714-123456-abcdef"}],
            "supersedes": [],
            "conflicts_with": [],
        },
        "# Claim\n\nPromotions must check the current digest before approval.",
    )


def candidate(tmp_path: Path) -> SimpleNamespace:
    repository = wiki(tmp_path)
    value = entry()
    path = repository.write_candidate(value)
    return SimpleNamespace(id=value.id, path=path, digest=_digest(path), repository=repository, entry=value)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_candidate_proposal_rejects_missing_required_fields(tmp_path: Path) -> None:
    path = write_proposal(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    del payload["summary"]
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(AppError, match="summary"):
        CandidateProposal.from_json(path)


def test_candidate_proposal_rejects_empty_evidence(tmp_path: Path) -> None:
    path = write_proposal(tmp_path, sources=[])

    with pytest.raises(AppError, match="evidence"):
        CandidateProposal.from_json(path)


def test_candidate_proposal_rejects_oversized_raw_logs(tmp_path: Path) -> None:
    path = write_proposal(tmp_path, raw_logs="x" * 70000)

    with pytest.raises(AppError, match="raw logs"):
        CandidateProposal.from_json(path)


def test_candidate_proposal_rejects_unsupported_confidence(tmp_path: Path) -> None:
    path = write_proposal(tmp_path, confidence="extreme")

    with pytest.raises(AppError, match="confidence"):
        CandidateProposal.from_json(path)


def test_agent_proposal_is_written_only_to_candidates(tmp_path: Path) -> None:
    repository = wiki(tmp_path)
    service = WikiService(repository)

    entry = service.propose(write_proposal(tmp_path))

    assert entry.status is KnowledgeStatus.CANDIDATE
    assert (repository.root / "candidates" / f"{entry.id}.md").is_file()
    assert not (repository.root / "approved" / f"{entry.id}.md").exists()


def test_promote_rejects_stale_candidate_digest(tmp_path: Path) -> None:
    candidate_value = candidate(tmp_path)
    candidate_value.path.write_text(candidate_value.path.read_text(encoding="utf-8") + "\nchanged\n", encoding="utf-8")
    service = WikiService(candidate_value.repository)

    with pytest.raises(AppError, match="candidate changed since review"):
        service.promote(candidate_value.id, reviewer="alice", expected_digest=candidate_value.digest)


def test_promote_validates_references_and_moves_file(tmp_path: Path) -> None:
    repository = wiki(tmp_path)
    approved_target = entry()
    (repository.root / "approved" / "KW-rule-existing-001.md").write_text(
        repository.serialize(
            KnowledgeEntry.from_parts(
                {
                    "id": "KW-rule-existing-001",
                    "title": "Existing approved knowledge",
                    "type": "rule",
                    "status": "approved",
                    "summary": "Existing approved knowledge.",
                    "scope": {
                        "repos": ["demo"],
                        "services": ["workflow"],
                        "paths": [],
                        "languages": [],
                        "phases": ["implement"],
                    },
                    "tags": [],
                    "owners": ["team-wiki"],
                    "reviewers": ["alice"],
                    "created_at": date(2026, 7, 1),
                    "reviewed_at": date(2026, 7, 2),
                    "review_after": date(2026, 10, 14),
                    "sources": [{"kind": "human", "ref": "alice"}],
                    "supersedes": [],
                    "conflicts_with": [],
                },
                "# Existing\n\nBody",
            )
        ),
        encoding="utf-8",
    )
    approved_target = KnowledgeEntry.from_parts(
        {
            "id": approved_target.id,
            "title": approved_target.title,
            "type": approved_target.type.value,
            "status": "candidate",
            "summary": approved_target.summary,
            "scope": {
                "repos": ["demo"],
                "services": ["workflow"],
                "paths": [],
                "languages": [],
                "phases": ["implement"],
            },
            "tags": ["wiki", "lifecycle"],
            "owners": ["team-wiki"],
            "reviewers": [],
            "created_at": date(2026, 7, 14),
            "reviewed_at": None,
            "review_after": date(2026, 10, 14),
            "sources": [{"kind": "run", "ref": "RUN-20260714-123456-abcdef"}],
            "supersedes": ["KW-rule-existing-001"],
            "conflicts_with": [],
        },
        approved_target.body,
    )
    candidate_path = repository.write_candidate(approved_target)
    service = WikiService(repository)

    promoted = service.promote(approved_target.id, reviewer="alice", expected_digest=_digest(candidate_path))

    assert promoted.status is KnowledgeStatus.APPROVED
    assert promoted.reviewers == ("alice",)
    assert promoted.reviewed_at == date.today()
    assert (repository.root / "approved" / f"{promoted.id}.md").is_file()
    assert not (repository.root / "candidates" / f"{promoted.id}.md").exists()


def test_reject_appends_lifecycle_note_and_archives(tmp_path: Path) -> None:
    candidate_value = candidate(tmp_path)
    service = WikiService(candidate_value.repository)

    archived_path = service.reject(
        candidate_value.id,
        reviewer="alice",
        reason="superseded by a later approved decision",
        expected_digest=candidate_value.digest,
    )

    text = archived_path.read_text(encoding="utf-8")
    assert archived_path.parent.name == "archive"
    assert "Lifecycle note" in text
    assert "reviewer: alice" in text
    assert "reason: superseded by a later approved decision" in text


def test_archive_rejects_stale_approved_digest(tmp_path: Path) -> None:
    repository = wiki(tmp_path)
    approved = KnowledgeEntry.from_parts(
        {
            "id": "KW-rule-deterministic-001",
            "title": "Promote deterministic wiki knowledge",
            "type": "rule",
            "status": "approved",
            "summary": "Approved knowledge should not depend on stale candidate content.",
            "scope": {
                "repos": ["demo"],
                "services": ["workflow"],
                "paths": [],
                "languages": [],
                "phases": ["implement"],
            },
            "tags": ["wiki", "lifecycle"],
            "owners": ["team-wiki"],
            "reviewers": ["alice"],
            "created_at": date(2026, 7, 14),
            "reviewed_at": date(2026, 7, 15),
            "review_after": date(2026, 10, 14),
            "sources": [{"kind": "run", "ref": "RUN-20260714-123456-abcdef"}],
            "supersedes": [],
            "conflicts_with": [],
        },
        "# Claim\n\nPromotions must check the current digest before approval.",
    )
    approved_path = repository.root / "approved" / f"{approved.id}.md"
    approved_path.write_text(repository.serialize(approved), encoding="utf-8")
    stale_digest = _digest(approved_path)
    approved_path.write_text(approved_path.read_text(encoding="utf-8") + "\nchanged\n", encoding="utf-8")
    service = WikiService(repository)

    with pytest.raises(AppError, match="approved entry changed since review"):
        service.archive(approved.id, reviewer="alice", reason="cleanup", expected_digest=stale_digest)
