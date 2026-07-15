import json
from pathlib import Path

import pytest

from ai_workflow.contracts.artifacts import ArtifactRef
from ai_workflow.contracts.packets import DispatchPacket
from ai_workflow.errors import AppError
from ai_workflow.workflow.dispatch import OWNER_CONTRACT, render_prompt_file
from ai_workflow.workflow.models import Phase


def _packet(tmp_path: Path, **changes: object) -> DispatchPacket:
    values: dict[str, object] = {
        "run_id": "RUN-20260715-120000-abcdef",
        "phase": Phase.VERIFY,
        "child": "unit_test",
        "attempt_id": "verify-1-abcdef",
        "source_revision": "abc123",
        "requirement": "Preserve the original requirement exactly.",
        "execution_mode": "rerun",
        "rerun_reason": "Unit tests exposed an unhandled branch.",
        "owner_contract_path": str(tmp_path / "agents" / "test-runner.md"),
        "common_contract_path": str(tmp_path / "agents" / "common-phase-contract.md"),
        "allowed_input_paths": ("src", "tests/unit"),
        "allowed_output_path": "artifacts/verify-unit-test.md",
        "commands": {
            "unit_test": (".venv/bin/python", "-m", "pytest", "tests/unit", "-q")
        },
        "knowledge_packet": {
            "path": str(tmp_path / "knowledge" / "unit-test.json"),
            "sha256": "b" * 64,
        },
        "prior_artifacts": (
            ArtifactRef(
                path="artifacts/implementation.md",
                sha256="a" * 64,
                schema_version=2,
                phase=Phase.IMPLEMENT,
                child="code",
                source_revision="abc123",
            ),
        ),
    }
    values.update(changes)
    return DispatchPacket(**values)  # type: ignore[arg-type]


def _write_packet(tmp_path: Path, payload: dict[str, object]) -> Path:
    path = tmp_path / "dispatch-packet.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_dispatch_packet_round_trips_schema_v2(tmp_path: Path) -> None:
    packet = _packet(tmp_path)

    loaded = DispatchPacket.load(_write_packet(tmp_path, packet.to_dict()))

    assert loaded == packet
    assert packet.to_dict()["schema_version"] == 2
    assert packet.to_dict()["commands"] == {
        "unit_test": [".venv/bin/python", "-m", "pytest", "tests/unit", "-q"]
    }


@pytest.mark.parametrize("mutation", ["unknown", "missing", "schema"])
def test_dispatch_packet_rejects_invalid_top_level_contract(
    tmp_path: Path, mutation: str
) -> None:
    payload = _packet(tmp_path).to_dict()
    if mutation == "unknown":
        payload["unexpected"] = True
    elif mutation == "missing":
        del payload["child"]
    else:
        payload["schema_version"] = 1

    with pytest.raises(ValueError):
        DispatchPacket.load(_write_packet(tmp_path, payload))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("run_id", ""),
        ("child", "  "),
        ("attempt_id", ""),
        ("source_revision", "  "),
        ("requirement", ""),
    ],
)
def test_dispatch_packet_rejects_blank_identities(
    tmp_path: Path, field: str, value: str
) -> None:
    payload = _packet(tmp_path).to_dict()
    payload[field] = value

    with pytest.raises(ValueError, match=field):
        DispatchPacket.load(_write_packet(tmp_path, payload))


@pytest.mark.parametrize("field", ["owner_contract_path", "common_contract_path"])
def test_dispatch_packet_requires_absolute_contract_paths(
    tmp_path: Path, field: str
) -> None:
    payload = _packet(tmp_path).to_dict()
    payload[field] = "skills/agents/contract.md"

    with pytest.raises(ValueError, match=f"{field} must be absolute"):
        DispatchPacket.load(_write_packet(tmp_path, payload))


@pytest.mark.parametrize(
    "knowledge",
    [
        {"path": "knowledge/packet.json", "sha256": "b" * 64},
        {"path": "/knowledge/packet.json", "sha256": "B" * 64},
        {"path": "/knowledge/packet.json", "sha256": "b" * 63},
        {"path": "/knowledge/packet.json", "sha256": "b" * 64, "extra": "x"},
    ],
)
def test_dispatch_packet_requires_exact_absolute_knowledge_reference(
    tmp_path: Path, knowledge: dict[str, str]
) -> None:
    payload = _packet(tmp_path).to_dict()
    payload["knowledge_packet"] = knowledge

    with pytest.raises(ValueError, match="knowledge packet"):
        DispatchPacket.load(_write_packet(tmp_path, payload))


@pytest.mark.parametrize(
    ("mode", "reason"),
    [
        ("fresh", "unexpected reason"),
        ("rerun", None),
        ("rerun", "  "),
        ("retry", "reason"),
    ],
)
def test_dispatch_packet_rejects_mode_reason_mismatch(
    tmp_path: Path, mode: str, reason: str | None
) -> None:
    payload = _packet(tmp_path).to_dict()
    payload["execution_mode"] = mode
    payload["rerun_reason"] = reason

    with pytest.raises(ValueError, match="execution mode and rerun reason"):
        DispatchPacket.load(_write_packet(tmp_path, payload))


@pytest.mark.parametrize(
    "path",
    ["/absolute/path", "../escape", "src/../escape", "./src", "", "src//module"],
)
def test_dispatch_packet_rejects_unsafe_allowed_input_paths(
    tmp_path: Path, path: str
) -> None:
    payload = _packet(tmp_path).to_dict()
    payload["allowed_input_paths"] = [path]

    with pytest.raises(ValueError, match="allowed_input_paths"):
        DispatchPacket.load(_write_packet(tmp_path, payload))


@pytest.mark.parametrize("path", ["/absolute/path", "../escape", "./out.md", ""])
def test_dispatch_packet_rejects_unsafe_allowed_output_path(
    tmp_path: Path, path: str
) -> None:
    payload = _packet(tmp_path).to_dict()
    payload["allowed_output_path"] = path

    with pytest.raises(ValueError, match="allowed_output_path"):
        DispatchPacket.load(_write_packet(tmp_path, payload))


def test_owner_contract_mapping_is_exact() -> None:
    assert OWNER_CONTRACT == {
        "spec.spec": "spec-writer.md",
        "plan.solution": "planner.md",
        "plan.test_strategy": "planner.md",
        "implement.code": "coder.md",
        "verify.build": "test-runner.md",
        "verify.unit_test": "test-runner.md",
        "verify.integration_test": "test-runner.md",
        "verify.code_review": "code-reviewer.md",
    }


def test_prompt_contains_complete_dispatch_contract(tmp_path: Path) -> None:
    packet = _packet(tmp_path)
    prompt_path = tmp_path / "attempt" / "prompt.md"

    assert render_prompt_file(packet, prompt_path) == prompt_path
    prompt = prompt_path.read_text(encoding="utf-8")

    assert packet.requirement in prompt
    assert packet.owner_contract_path in prompt
    assert packet.common_contract_path in prompt
    assert "src" in prompt and "tests/unit" in prompt
    assert packet.allowed_output_path in prompt
    assert '".venv/bin/python"' in prompt
    assert '"execution_mode": "rerun"' in prompt
    assert packet.rerun_reason in prompt
    assert packet.knowledge_packet["sha256"] in prompt
    assert "Read only the allowed inputs." in prompt
    assert "Write only the assigned artifact." in prompt
    assert "Do not edit workflow state." in prompt
    assert "Do not read raw Wiki Markdown." in prompt
    assert "Return only schema-v2 ChildResult JSON." in prompt
    json_block = prompt.split("```json\n", 1)[1].split("\n```", 1)[0]
    assert json.loads(json_block) == packet.to_dict()


def test_prompt_render_is_identical_and_rejects_conflicting_content(
    tmp_path: Path,
) -> None:
    prompt_path = tmp_path / "attempt" / "prompt.md"
    packet = _packet(tmp_path)
    render_prompt_file(packet, prompt_path)
    original = prompt_path.read_bytes()

    assert render_prompt_file(packet, prompt_path) == prompt_path
    assert prompt_path.read_bytes() == original

    with pytest.raises(AppError) as error:
        render_prompt_file(
            _packet(tmp_path, requirement="A different original requirement."),
            prompt_path,
        )
    assert error.value.code == "dispatch_prompt_conflict"
    assert prompt_path.read_bytes() == original
