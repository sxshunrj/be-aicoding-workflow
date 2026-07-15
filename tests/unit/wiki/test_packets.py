import json
from datetime import date

from ai_workflow.wiki.models import KnowledgeEntry, KnowledgeScope, KnowledgeStatus, KnowledgeType
from ai_workflow.wiki.search import KnowledgeQuery, SearchLimits
from ai_workflow.wiki.service import WikiService


class Repository:
    def paths(self): return ["one"]
    def read(self, path):
        return KnowledgeEntry(
            "KW-rule-001",
            "Retry",
            KnowledgeType.RULE,
            KnowledgeStatus.APPROVED,
            "Use retries",
            KnowledgeScope(),
            ("retry",),
            ("owner",),
            ("reviewer",),
            date(2025, 1, 1),
            date(2025, 1, 2),
            date(2030, 1, 1),
            ({"kind": "human", "ref": "x"},),
            (),
            (),
            "bounded body " * 80,
        )


def test_packet_is_bounded_and_digest_matches_canonical_content(tmp_path) -> None:
    output = tmp_path / "packet.json"
    packet = WikiService(Repository()).create_packet(KnowledgeQuery(text="retry"), output, SearchLimits(1, 5000))
    payload = json.loads(output.read_text())
    assert packet.selected_ids == ("KW-rule-001",)
    assert payload["digest"] == packet.digest
    assert len(output.read_text()) <= 5000
    assert len(payload["entries"][0]["content"]) < len("bounded body " * 80)
    assert "use retries" in payload["entries"][0]["content"].casefold()
