from pathlib import Path

from ai_workflow.contracts.artifacts import ChildResult


def test_skill_never_instructs_agent_to_edit_state_directly() -> None:
    skill = Path("skills/ai-workflow/SKILL.md").read_text(encoding="utf-8")
    assert "Never edit state.yaml directly" in skill
    assert "ai-workflow workflow submit" in skill
    assert "ai-workflow wiki propose" in skill


def test_each_phase_fixture_parses_as_child_result() -> None:
    for path in sorted(Path("tests/contract/fixtures").glob("*-result.json")):
        result = ChildResult.from_json(path)
        assert result.status in {"completed", "unable_to_complete"}
