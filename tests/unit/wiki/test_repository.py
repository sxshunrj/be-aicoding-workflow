from datetime import date

from ai_workflow.wiki.models import KnowledgeEntry, KnowledgeStatus
from ai_workflow.wiki.repository import WikiRepository


def entry() -> KnowledgeEntry:
    return KnowledgeEntry.from_parts({
        "id": "KW-rule-001", "title": "Rule", "type": "rule", "status": "candidate",
        "summary": "Summary", "scope": {"repos": [], "services": [], "paths": [],
        "languages": [], "phases": []}, "tags": [], "owners": ["team"], "reviewers": [],
        "created_at": date(2026, 7, 14), "reviewed_at": None,
        "review_after": date(2026, 10, 14),
        "sources": [{"kind": "human", "ref": "alice"}],
        "supersedes": [], "conflicts_with": [],
    }, "# Rule\n\nBody")


def test_writes_reads_lists_and_moves_entry(tmp_path) -> None:
    repository = WikiRepository(tmp_path)
    path = repository.write_candidate(entry())
    assert repository.read(path).id == "KW-rule-001"
    assert [item.id for item in repository.list(KnowledgeStatus.CANDIDATE)] == ["KW-rule-001"]
    moved = repository.move("KW-rule-001", KnowledgeStatus.CANDIDATE, KnowledgeStatus.APPROVED)
    assert moved.parent.name == "approved"
    assert not path.exists()

