from datetime import date

from ai_workflow.wiki.models import KnowledgeEntry, KnowledgeScope, KnowledgeStatus, KnowledgeType
from ai_workflow.wiki.search import KnowledgeQuery, KnowledgeSearcher, SearchLimits


def entry(identifier, *, title, status=KnowledgeStatus.APPROVED, repos=(), tags=(), body="", review_after=date(2030, 1, 1), conflicts=()):
    return KnowledgeEntry(identifier, title, KnowledgeType.RULE, status, "summary", KnowledgeScope(repos=tuple(repos)), tuple(tags), ("owner",), ("reviewer",), date(2025, 1, 1), date(2025, 1, 2), review_after, ({"kind": "human", "ref": "review"},), (), tuple(conflicts), body or title)


def test_exact_scope_and_title_match_rank_first() -> None:
    exact = entry("KW-rule-001", title="Payment retry", repos=["demo"], tags=["retry"])
    broad = entry("KW-rule-002", title="General reliability", body="Payment retry")
    results = KnowledgeSearcher([broad, exact]).search(KnowledgeQuery(repository="demo", phase="implement", text="payment retry"), SearchLimits(8, 12000))
    assert [result.entry.id for result in results] == ["KW-rule-001", "KW-rule-002"]
    assert "repository:demo" in results[0].match_reasons


def test_candidates_are_never_returned_by_default() -> None:
    candidate = entry("KW-rule-003", title="Payment retry", status=KnowledgeStatus.CANDIDATE)
    assert KnowledgeSearcher([candidate]).search(KnowledgeQuery(text="payment retry"), SearchLimits(8, 12000)) == ()


def test_search_warns_using_injected_date_and_is_deterministic() -> None:
    stale = entry("KW-rule-004", title="Retry", review_after=date(2026, 1, 1), conflicts=("KW-rule-005",))
    result = KnowledgeSearcher([stale], today=lambda: date(2026, 7, 14)).search(KnowledgeQuery(text="retry"), SearchLimits(8, 12000))[0]
    assert result.warnings == ("review overdue since 2026-01-01", "conflicts with KW-rule-005")


def test_filtered_queries_do_not_return_unrelated_broad_scope_entries() -> None:
    broad = entry("KW-rule-005", title="General note")
    results = KnowledgeSearcher([broad]).search(KnowledgeQuery(repository="demo"), SearchLimits(8, 12000))
    assert results == ()
