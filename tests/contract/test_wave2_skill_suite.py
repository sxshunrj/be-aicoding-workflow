from pathlib import Path


EXPECTED_SKILLS = (
    "ai-ci-failure-triage",
    "ai-git-handoff",
    "ai-integration-test-checklists",
    "ai-integration-test-generator",
    "ai-integration-test-v2",
    "ai-knowledge-governance",
    "ai-knowledge-reflection",
    "ai-small-tdd-change",
    "ai-workflow-harness",
    "ai-workflow-harness-grill",
    "ai-workflow-init",
)


def test_wave2_skill_suite_contains_all_eleven_skills() -> None:
    assert tuple(sorted(path.name for path in Path("skills").iterdir() if path.is_dir())) == EXPECTED_SKILLS


def test_wave2_skill_suite_has_frontmatter_and_metadata() -> None:
    for name in EXPECTED_SKILLS:
        root = Path("skills") / name
        skill = (root / "SKILL.md").read_text(encoding="utf-8")
        metadata = (root / "agents" / "openai.yaml").read_text(encoding="utf-8")
        assert f"name: {name}" in skill
        display = next(line for line in metadata.splitlines() if "display_name:" in line)
        assert display.isascii()
        assert "short_description:" in metadata
        assert "default_prompt:" in metadata
