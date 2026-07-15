from __future__ import annotations

import json
from pathlib import Path

from ai_workflow.cli import main


def _config(root: Path) -> None:
    (root / ".ai-workflow.yaml").write_text("repository: demo\nwiki_path: wiki\n", encoding="utf-8")


def _wiki(root: Path) -> None:
    for name in ("approved", "candidates", "archive"):
        (root / "wiki" / name).mkdir(parents=True, exist_ok=True)
    (root / "wiki" / "taxonomy.yaml").write_text(
        "schema_version: 1\n"
        "types: [rule, decision, pattern, pitfall, procedure]\n"
        "phases: [spec, plan, implement, verify]\n",
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


def test_candidate_promotion_round_trip(tmp_path: Path, capsys) -> None:
    _config(tmp_path)
    _wiki(tmp_path)
    proposal_path = _proposal(tmp_path)

    status = main(["wiki", "propose", "--wiki", str(tmp_path / "wiki"), "--proposal", str(proposal_path)])
    proposed = json.loads(capsys.readouterr().out)
    assert status == 0

    status = main([
        "wiki",
        "promote",
        "--wiki",
        str(tmp_path / "wiki"),
        "--id",
        proposed["data"]["id"],
        "--reviewer",
        "alice",
        "--expected-digest",
        proposed["data"]["digest"],
    ])
    promoted = json.loads(capsys.readouterr().out)
    assert status == 0
    assert promoted["data"]["status"] == "approved"

    status = main([
        "wiki",
        "search",
        "--wiki",
        str(tmp_path / "wiki"),
        "--repository",
        "demo",
        "--text",
        "deterministic wiki knowledge",
    ])
    search = json.loads(capsys.readouterr().out)
    assert status == 0
    assert [item["id"] for item in search["data"]] == [proposed["data"]["id"]]
