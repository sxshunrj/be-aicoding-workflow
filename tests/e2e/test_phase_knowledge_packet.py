import hashlib
import json
from datetime import date
from pathlib import Path

import pytest

from ai_workflow.contracts.artifacts import ArtifactRef, ChildResult
from ai_workflow.contracts.packets import DispatchPacket
from ai_workflow.errors import AppError
from ai_workflow.workflow.models import Phase
from ai_workflow.workflow.service import WorkflowService
from ai_workflow.wiki.models import (
    KnowledgeEntry,
    KnowledgeScope,
    KnowledgeStatus,
    KnowledgeType,
)
from ai_workflow.wiki.repository import WikiRepository


def _skill_dir(root: Path) -> Path:
    contracts = root / "skill" / "references" / "agents"
    contracts.mkdir(parents=True)
    for name in ("common-phase-contract.md", "spec-writer.md"):
        (contracts / name).write_text(f"# {name}\n", encoding="utf-8")
    return contracts.parents[1]


def test_begin_writes_child_packet_and_stage_validates_citations(tmp_path: Path) -> None:
    (tmp_path / ".ai-workflow.yaml").write_text(
        "repository: demo\n", encoding="utf-8"
    )
    for name in ("approved", "candidates", "archive"):
        (tmp_path / "wiki" / name).mkdir(parents=True, exist_ok=True)
    (tmp_path / "wiki" / "taxonomy.yaml").write_text(
        "schema_version: 1\ntypes: [rule]\nphases: [spec, plan, implement, verify]\n",
        encoding="utf-8",
    )
    entry = KnowledgeEntry(
        "KW-rule-001",
        "Spec rule",
        KnowledgeType.RULE,
        KnowledgeStatus.APPROVED,
        "Use it",
        KnowledgeScope(repos=("demo",), phases=("spec",)),
        (),
        ("owner",),
        ("reviewer",),
        date(2025, 1, 1),
        date(2025, 1, 2),
        date(2030, 1, 1),
        ({"kind": "human", "ref": "x"},),
        (),
        (),
        "Body",
    )
    wiki = WikiRepository(tmp_path / "wiki")
    (tmp_path / "wiki" / "approved" / "KW-rule-001.md").write_text(
        wiki.serialize(entry), encoding="utf-8"
    )
    service = WorkflowService(tmp_path, id_factory=lambda: "abcdef")
    run = service.init(tmp_path, "abc123", "Use approved specification guidance")
    attempt = service.begin(run.run_id, Phase.SPEC, _skill_dir(tmp_path))
    dispatch = DispatchPacket.load(attempt.dispatch_plan[0].packet_file)
    packet = json.loads(
        Path(dispatch.knowledge_packet["path"]).read_text(encoding="utf-8")
    )
    assert packet["selected_ids"] == ["KW-rule-001"]

    artifact = tmp_path / dispatch.allowed_output_path
    artifact.parent.mkdir(parents=True)
    artifact.write_text("spec", encoding="utf-8")
    ref = ArtifactRef(
        dispatch.allowed_output_path,
        hashlib.sha256(b"spec").hexdigest(),
        2,
        Phase.SPEC,
        "spec",
        "abc123",
    )
    result_path = tmp_path / "result.json"
    bad = ChildResult(
        run.run_id,
        Phase.SPEC,
        "spec",
        attempt.attempt_id,
        "fresh",
        "completed",
        "done",
        ref,
        (),
        ("KW-rule-999",),
    )
    bad.write(result_path)
    with pytest.raises(AppError, match="not in phase packet"):
        service.stage(run.run_id, attempt.attempt_id, "spec", result_path)

    ChildResult(
        run.run_id,
        Phase.SPEC,
        "spec",
        attempt.attempt_id,
        "fresh",
        "completed",
        "done",
        ref,
        (),
        ("KW-rule-001",),
    ).write(result_path)
    service.stage(run.run_id, attempt.attempt_id, "spec", result_path)
    service.finalize(run.run_id, attempt.attempt_id)

    assert service.summary(run.run_id).cited_knowledge_ids == ("KW-rule-001",)
