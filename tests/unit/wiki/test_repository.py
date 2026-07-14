from datetime import date

from ai_workflow.wiki.models import KnowledgeEntry, KnowledgeStatus
import os
from dataclasses import replace

import pytest

from ai_workflow.errors import AppError
from ai_workflow.wiki.repository import WikiRepository


def wiki(tmp_path):
    for name in ("approved", "candidates", "archive"):
        (tmp_path / name).mkdir()
    (tmp_path / "taxonomy.yaml").write_text("schema_version: 1\ntypes: [rule]\nphases: [implement]\n")
    return WikiRepository(tmp_path)


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
    repository = wiki(tmp_path)
    path = repository.write_candidate(entry())
    assert repository.read(path).id == "KW-rule-001"
    assert [item.id for item in repository.list(KnowledgeStatus.CANDIDATE)] == ["KW-rule-001"]
    with pytest.raises(AppError, match="status does not match target"):
        repository.move("KW-rule-001", KnowledgeStatus.CANDIDATE, KnowledgeStatus.APPROVED)


def test_moves_only_entry_already_reviewed_for_target(tmp_path) -> None:
    repository = wiki(tmp_path)
    approved = replace(entry(), status=KnowledgeStatus.APPROVED, reviewers=("alice",), reviewed_at=date(2026, 7, 14))
    source = tmp_path / "candidates" / f"{approved.id}.md"
    source.write_text(repository.serialize(approved), encoding="utf-8")
    moved = repository.move(approved.id, "candidate", "approved")
    assert moved.parent.name == "approved" and not source.exists()


def test_requires_complete_real_wiki_layout(tmp_path) -> None:
    with pytest.raises(AppError, match="wiki root"):
        WikiRepository(tmp_path / "missing")
    tmp_path.joinpath("approved").mkdir()
    with pytest.raises(AppError, match="lifecycle directory"):
        WikiRepository(tmp_path)


def test_rejects_traversal_symlinks_and_collisions(tmp_path) -> None:
    repository = wiki(tmp_path)
    with pytest.raises(AppError, match="knowledge id"):
        repository.move("../escape", "candidate", "approved")
    outside = tmp_path.parent / "outside.md"
    outside.write_text("outside")
    link = tmp_path / "candidates" / "KW-rule-001.md"
    link.symlink_to(outside)
    with pytest.raises(AppError, match="symbolic link"):
        repository.read(link)
    link.unlink()
    repository.write_candidate(entry())
    with pytest.raises(AppError, match="already exists"):
        repository.write_candidate(entry())


def test_atomic_write_cleans_temp_on_replace_failure(tmp_path, monkeypatch) -> None:
    repository = wiki(tmp_path)
    monkeypatch.setattr(os, "replace", lambda *_: (_ for _ in ()).throw(OSError("boom")))
    with pytest.raises(AppError, match="cannot write"):
        repository.write_candidate(entry())
    assert list((tmp_path / "candidates").iterdir()) == []


def test_front_matter_delimiters_must_be_exact_lines(tmp_path) -> None:
    repository = wiki(tmp_path)
    path = tmp_path / "candidates" / "KW-rule-001.md"
    content = repository.serialize(entry()).replace("summary: Summary", "summary: |-\n  ---")
    path.write_text(content, encoding="utf-8")
    assert repository.read(path).summary == "---"
    path.write_text(" ---\nid: KW-rule-001\n---\nBody", encoding="utf-8")
    with pytest.raises(AppError, match="must begin"):
        repository.read(path)


def test_move_refuses_existing_target_file_or_symlink(tmp_path) -> None:
    repository = wiki(tmp_path)
    approved = replace(entry(), status=KnowledgeStatus.APPROVED, reviewers=("alice",), reviewed_at=date(2026, 7, 14))
    source = tmp_path / "candidates" / f"{approved.id}.md"
    source.write_text(repository.serialize(approved), encoding="utf-8")
    target = tmp_path / "approved" / source.name
    target.write_text("occupied", encoding="utf-8")
    with pytest.raises(AppError, match="already exists"):
        repository.move(approved.id, "candidate", "approved")
    assert source.exists() and target.read_text() == "occupied"
