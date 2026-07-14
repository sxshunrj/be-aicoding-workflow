from dataclasses import replace
from datetime import date

from ai_workflow.wiki.models import KnowledgeStatus
from ai_workflow.wiki.repository import WikiRepository
from ai_workflow.wiki.service import WikiService
from tests.unit.wiki.test_repository import entry, wiki


def _store(repository, directory, value, filename=None):
    path = repository.root / directory / (filename or f"{value.id}.md")
    path.write_text(repository.serialize(value), encoding="utf-8")


def test_lint_accepts_all_status_directory_mappings_and_cross_reference(tmp_path) -> None:
    repository = wiki(tmp_path)
    candidate = entry()
    approved = replace(candidate, id="KW-rule-002", status=KnowledgeStatus.APPROVED,
                       reviewers=("alice",), reviewed_at=date(2026, 7, 14),
                       conflicts_with=(candidate.id,))
    archived = replace(candidate, id="KW-rule-003", status=KnowledgeStatus.ARCHIVED)
    superseded = replace(candidate, id="KW-rule-004", status=KnowledgeStatus.SUPERSEDED,
                         supersedes=(archived.id,))
    for directory, value in (("candidates", candidate), ("approved", approved),
                             ("archive", archived), ("archive", superseded)):
        _store(repository, directory, value)
    assert WikiService(repository).lint().valid is True


def test_lint_reports_global_duplicate_missing_and_self_references(tmp_path) -> None:
    repository = wiki(tmp_path)
    bad = replace(entry(), supersedes=("KW-rule-999",), conflicts_with=(entry().id,))
    _store(repository, "candidates", bad)
    _store(repository, "archive", replace(bad, status=KnowledgeStatus.ARCHIVED), "duplicate.md")
    issues = WikiService(repository).lint().issues
    assert any("duplicate knowledge id" in issue for issue in issues)
    assert any("does not exist" in issue for issue in issues)
    assert any("must not reference itself" in issue for issue in issues)


def test_lint_reports_every_directory_status_mismatch(tmp_path) -> None:
    repository = wiki(tmp_path)
    _store(repository, "approved", entry())
    _store(repository, "candidates", replace(entry(), id="KW-rule-002", status=KnowledgeStatus.ARCHIVED))
    _store(repository, "archive", replace(entry(), id="KW-rule-003", status=KnowledgeStatus.APPROVED,
                                           reviewers=("alice",), reviewed_at=date(2026, 7, 14)))
    issues = WikiService(repository).lint().issues
    assert sum("directory does not match status" in issue for issue in issues) == 3
