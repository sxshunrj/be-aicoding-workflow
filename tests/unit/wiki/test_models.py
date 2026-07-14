from datetime import date

import pytest

from ai_workflow.errors import AppError
from ai_workflow.wiki.models import KnowledgeEntry, KnowledgeStatus


def valid_metadata(status: str = "candidate") -> dict[str, object]:
    return {
        "id": "KW-rule-001", "title": "Rule", "type": "rule", "status": status,
        "summary": "Summary", "scope": {"repos": [], "services": [], "paths": [],
        "languages": [], "phases": ["implement"]}, "tags": [], "owners": ["team"],
        "reviewers": ["alice"] if status == "approved" else [],
        "created_at": date(2026, 7, 14),
        "reviewed_at": date(2026, 7, 14) if status == "approved" else None,
        "review_after": date(2026, 10, 14),
        "sources": [{"kind": "run", "ref": "RUN-1"}],
        "supersedes": [], "conflicts_with": [],
    }


def test_rejects_approved_entry_without_reviewer() -> None:
    metadata = valid_metadata(status="approved")
    metadata["reviewers"] = []
    with pytest.raises(AppError, match="approved knowledge requires a reviewer"):
        KnowledgeEntry.from_parts(metadata, "# Rule\n\nBody")


def test_candidate_requires_run_evidence() -> None:
    metadata = valid_metadata(status="candidate")
    metadata["sources"] = []
    with pytest.raises(AppError, match="candidate knowledge requires a source"):
        KnowledgeEntry.from_parts(metadata, "# Rule\n\nBody")


def test_parses_valid_entry() -> None:
    entry = KnowledgeEntry.from_parts(valid_metadata(), "# Rule\n\nBody")
    assert entry.status is KnowledgeStatus.CANDIDATE
    assert entry.scope.phases == ("implement",)

