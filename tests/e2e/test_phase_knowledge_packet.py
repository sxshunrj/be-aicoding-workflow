import hashlib
import json
from datetime import date

import pytest

from ai_workflow.contracts.artifacts import ArtifactRef, ChildResult
from ai_workflow.contracts.packets import PhasePacket
from ai_workflow.errors import AppError
from ai_workflow.workflow.models import Phase
from ai_workflow.workflow.service import WorkflowService
from ai_workflow.wiki.models import KnowledgeEntry, KnowledgeScope, KnowledgeStatus, KnowledgeType
from ai_workflow.wiki.repository import WikiRepository


def test_begin_writes_packet_and_submit_validates_citations(tmp_path) -> None:
    (tmp_path / ".ai-workflow.yaml").write_text("repository: demo\n", encoding="utf-8")
    for name in ("approved", "candidates", "archive"):
        (tmp_path / "wiki" / name).mkdir(parents=True, exist_ok=True)
    (tmp_path / "wiki" / "taxonomy.yaml").write_text("schema_version: 1\ntypes: [rule]\nphases: [spec, plan, implement, verify]\n", encoding="utf-8")
    entry = KnowledgeEntry("KW-rule-001", "Spec rule", KnowledgeType.RULE, KnowledgeStatus.APPROVED, "Use it", KnowledgeScope(repos=("demo",), phases=("spec",)), (), ("owner",), ("reviewer",), date(2025,1,1), date(2025,1,2), date(2030,1,1), ({"kind":"human","ref":"x"},), (), (), "Body")
    (tmp_path / "wiki" / "approved" / "KW-rule-001.md").write_text(WikiRepository(tmp_path / "wiki").serialize(entry), encoding="utf-8")
    service = WorkflowService(tmp_path, id_factory=lambda: "abcdef")
    run = service.init(tmp_path, "abc123")
    attempt = service.begin(run.run_id, Phase.SPEC)
    phase_packet = PhasePacket.load(attempt.packet_path)
    packet = json.loads(open(phase_packet.knowledge_packet["path"]).read())
    assert packet["selected_ids"] == ["KW-rule-001"]
    artifact = tmp_path / "spec.md"
    artifact.write_text("spec")
    ref = ArtifactRef(str(artifact), hashlib.sha256(b"spec").hexdigest(), 1, Phase.SPEC, "abc123")
    bad = tmp_path / "bad.json"
    ChildResult("completed", "done", ref, (), ("KW-rule-999",)).write(bad)
    with pytest.raises(AppError, match="not in phase packet"):
        service.submit(run.run_id, attempt.attempt_id, bad)
    ChildResult("completed", "done", ref, (), ("KW-rule-001",)).write(bad)
    service.submit(run.run_id, attempt.attempt_id, bad)
    assert service.summary(run.run_id).cited_knowledge_ids == ("KW-rule-001",)
