from pathlib import Path
import json
import re


SKILL_DIR = Path("skills/ai-knowledge-reflection")


def _read(relative: str = "SKILL.md") -> str:
    return (SKILL_DIR / relative).read_text(encoding="utf-8")


def test_reflection_skill_frontmatter_and_sequence_are_canonical() -> None:
    skill = _read()

    assert skill.startswith(
        "---\nname: ai-knowledge-reflection\n"
        "description: Use when ai-workflow run is completed or aborted and terminal cleanup needs evidence-backed knowledge reflection.\n"
        "---\n"
    )
    assert (
        "workflow reflect -> read packet -> search related approved knowledge -> write decision "
        "-> optional proposal -> workflow reflect-submit -> wiki propose"
    ) in skill
    for required in (
        "completed",
        "aborted",
        "knowledge-reflection-decision.json",
        "knowledge-proposal.json",
        "workflow reflect-submit",
        "wiki propose",
        "no_candidate",
        "candidate",
    ):
        assert required in skill


def test_reflection_skill_forbids_governance_or_direct_approved_writes() -> None:
    skill = _read()

    for forbidden_boundary in (
        "never call `wiki promote`",
        "never write `wiki/approved`",
        "reflection acceptance is not governance approval",
        "do not invent claims",
        "do not include secrets",
    ):
        assert forbidden_boundary in skill


def test_reflection_proposal_contract_defines_exact_decision_json() -> None:
    contract = _read("references/proposal-contract.md")
    match = re.search(r"```json\n(?P<payload>.*?)\n```", contract, re.DOTALL)
    assert match is not None

    payload = json.loads(match.group("payload"))

    assert set(payload) == {
        "schema_version",
        "run_id",
        "evidence_digest",
        "outcome",
        "reason",
    }
    assert payload == {
        "schema_version": 1,
        "run_id": "RUN-20260715-120000-abcdef",
        "evidence_digest": "a" * 64,
        "outcome": "no_candidate",
        "reason": "Evidence is run-specific and not reusable.",
    }


def test_reflection_proposal_contract_keeps_candidate_proposal_schema_unchanged() -> None:
    contract = _read("references/proposal-contract.md")

    for required in (
        "schema-v1 `CandidateProposal` JSON",
        "Do not add workflow-only fields to `CandidateProposal`",
        "{\"kind\": \"run\", \"ref\": run_id}",
        "rule",
        "pattern",
        "diagnostic",
        "decision",
        "pitfall",
        "workflow",
        "forbid raw secrets",
        "forbid invented claims",
        "forbid direct approved writes",
    ):
        assert required in contract


def test_reflection_skill_has_ui_metadata_and_reference_link() -> None:
    skill = _read()
    metadata = _read("agents/openai.yaml")

    assert "](references/proposal-contract.md)" in skill
    assert "display_name" in metadata
    assert "$ai-knowledge-reflection" in metadata
