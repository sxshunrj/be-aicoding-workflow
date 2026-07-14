import json

import pytest

from ai_workflow.contracts.artifacts import ArtifactRef, ChildResult, Finding
from ai_workflow.contracts.packets import PhasePacket
from ai_workflow.workflow.models import Phase


def test_child_result_round_trips_versioned_json(tmp_path) -> None:
    result = ChildResult(
        status="completed",
        summary="specification ready",
        artifact=ArtifactRef("spec.md", "a" * 64, 1, Phase.SPEC, "abc123"),
        findings=(Finding("F-1", "important", "detail"),),
    )
    path = tmp_path / "result.json"
    result.write(path)

    assert ChildResult.load(path) == result
    assert json.loads(path.read_text())["schema_version"] == 1


def test_child_result_rejects_unknown_schema_version(tmp_path) -> None:
    path = tmp_path / "result.json"
    path.write_text('{"schema_version":2}', encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported schema_version"):
        ChildResult.load(path)


def test_child_result_rejects_missing_schema_version_as_contract_error(tmp_path) -> None:
    path = tmp_path / "result.json"
    path.write_text('{"status":"completed"}', encoding="utf-8")

    with pytest.raises(ValueError, match="schema_version is required"):
        ChildResult.load(path)


def test_phase_packet_round_trips_versioned_json(tmp_path) -> None:
    packet = PhasePacket("RUN-20260714-123456-abcdef", Phase.PLAN, "plan-1-abcdef",
                         "abc123", {"cited_knowledge_ids": ["K-1"]}, (), None)
    path = tmp_path / "packet.json"
    packet.write(path)

    assert PhasePacket.load(path) == packet
