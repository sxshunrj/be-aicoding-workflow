import json
from datetime import date

from ai_workflow.cli import main
from ai_workflow.wiki.models import KnowledgeEntry, KnowledgeScope, KnowledgeStatus, KnowledgeType
from ai_workflow.wiki.repository import WikiRepository


def _wiki(root):
    for name in ("approved", "candidates", "archive"):
        (root / name).mkdir()
    (root / "taxonomy.yaml").write_text(
        "schema_version: 1\ntypes: [rule]\nphases: [implement]\n",
        encoding="utf-8",
    )
    entry = KnowledgeEntry(
        "KW-rule-001",
        "Payment retry",
        KnowledgeType.RULE,
        KnowledgeStatus.APPROVED,
        "Use transient fallback",
        KnowledgeScope(repos=("demo",), phases=("implement",)),
        ("retry",),
        ("owner",),
        ("reviewer",),
        date(2025, 1, 1),
        date(2025, 1, 2),
        date(2030, 1, 1),
        ({"kind": "human", "ref": "review"},),
        (),
        (),
        "Workflow body",
    )
    (root / "approved" / "KW-rule-001.md").write_text(
        WikiRepository(root).serialize(entry),
        encoding="utf-8",
    )


def test_wiki_search_and_packet_cli(tmp_path, capsys) -> None:
    _wiki(tmp_path)

    status = main([
        "wiki",
        "search",
        "--wiki",
        str(tmp_path),
        "--repository",
        "demo",
        "--text",
        "payment retry",
    ])
    search = json.loads(capsys.readouterr().out)
    assert status == 0
    assert search == {
        "ok": True,
        "data": [
            {
                "id": "KW-rule-001",
                "title": "Payment retry",
                "score": 80,
                "match_reasons": ["repository:demo", "title:payment", "title:retry"],
                "warnings": [],
            }
        ],
    }

    output = tmp_path / "packet.json"
    status = main([
        "wiki",
        "packet",
        "--wiki",
        str(tmp_path),
        "--repository",
        "demo",
        "--text",
        "payment retry",
        "--output",
        str(output),
    ])
    packet = json.loads(capsys.readouterr().out)
    assert status == 0
    assert packet["ok"] is True
    assert packet["data"]["path"] == str(output)
    assert packet["data"]["selected_ids"] == ["KW-rule-001"]
    assert json.loads(output.read_text(encoding="utf-8"))["digest"] == packet["data"]["sha256"]
