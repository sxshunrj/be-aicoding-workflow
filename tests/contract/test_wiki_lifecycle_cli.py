from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from ai_workflow.cli import main
from ai_workflow.wiki.models import KnowledgeEntry, KnowledgeScope, KnowledgeStatus, KnowledgeType
from ai_workflow.wiki.repository import WikiRepository


def _wiki(root: Path) -> None:
    for name in ("approved", "candidates", "archive"):
        (root / name).mkdir()
    (root / "taxonomy.yaml").write_text(
        "schema_version: 1\n"
        "types: [rule, decision, pattern, pitfall, procedure]\n"
        "phases: [implement]\n",
        encoding="utf-8",
    )
    approved = KnowledgeEntry(
        "KW-rule-existing-001",
        "Existing approved knowledge",
        KnowledgeType.RULE,
        KnowledgeStatus.APPROVED,
        "Existing approved knowledge.",
        KnowledgeScope(repos=("demo",), services=("workflow",), phases=("implement",)),
        (),
        ("team-wiki",),
        ("alice",),
        date(2026, 7, 1),
        date(2026, 7, 2),
        date(2026, 10, 14),
        ({"kind": "human", "ref": "alice"},),
        (),
        (),
        "# Existing\n\nBody",
    )
    (root / "approved" / "KW-rule-existing-001.md").write_text(
        WikiRepository(root).serialize(approved),
        encoding="utf-8",
    )


def _proposal(root: Path) -> Path:
    path = root / "proposal.json"
    path.write_text(
        json.dumps(
            {
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
        ),
        encoding="utf-8",
    )
    return path


def _call(capsys, argv: list[str]) -> tuple[int, dict[str, object]]:
    status = main(argv)
    return status, json.loads(capsys.readouterr().out)


def test_wiki_lifecycle_cli_round_trip(tmp_path: Path, capsys) -> None:
    _wiki(tmp_path)
    proposal_path = _proposal(tmp_path)

    status, proposed = _call(
        capsys,
        ["wiki", "propose", "--wiki", str(tmp_path), "--proposal", str(proposal_path)],
    )
    assert status == 0
    assert proposed["ok"] is True
    assert proposed["data"]["status"] == "candidate"
    candidate_path = Path(proposed["data"]["path"])
    candidate_digest = proposed["data"]["digest"]
    assert candidate_path.parent.name == "candidates"

    status, promoted = _call(
        capsys,
        [
            "wiki",
            "promote",
            "--wiki",
            str(tmp_path),
            "--id",
            proposed["data"]["id"],
            "--reviewer",
            "alice",
            "--expected-digest",
            candidate_digest,
        ],
    )
    assert status == 0
    assert promoted["data"]["status"] == "approved"
    assert Path(promoted["data"]["path"]).parent.name == "approved"

    second_proposal_path = _proposal(tmp_path)
    status, second_proposed = _call(
        capsys,
        ["wiki", "propose", "--wiki", str(tmp_path), "--proposal", str(second_proposal_path)],
    )
    assert status == 0

    status, rejected = _call(
        capsys,
        [
            "wiki",
            "reject",
            "--wiki",
            str(tmp_path),
            "--id",
            second_proposed["data"]["id"],
            "--reviewer",
            "alice",
            "--reason",
            "superseded by a later decision",
            "--expected-digest",
            second_proposed["data"]["digest"],
        ],
    )
    assert status == 0
    assert rejected["data"]["status"] == "archived"

    status, archived = _call(
        capsys,
        [
            "wiki",
            "archive",
            "--wiki",
            str(tmp_path),
            "--id",
            proposed["data"]["id"],
            "--reviewer",
            "alice",
            "--reason",
            "retired",
            "--expected-digest",
            promoted["data"]["digest"],
        ],
    )
    assert status == 0
    assert archived["data"]["status"] == "archived"


def test_wiki_lifecycle_cli_requires_arguments(tmp_path: Path, capsys) -> None:
    _wiki(tmp_path)
    status, payload = _call(capsys, ["wiki", "propose", "--wiki", str(tmp_path)])

    assert status != 0
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_arguments"
