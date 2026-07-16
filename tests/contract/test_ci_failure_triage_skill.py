from pathlib import Path


SKILL_DIR = Path("skills/ai-ci-failure-triage")


def _read(relative: str = "SKILL.md") -> str:
    return (SKILL_DIR / relative).read_text(encoding="utf-8")


def test_ci_triage_frontmatter_and_metadata_are_canonical() -> None:
    skill = _read()
    metadata = _read("agents/openai.yaml")
    assert skill.startswith(
        "---\nname: ai-ci-failure-triage\n"
        "description: Use when 用户要求收集 CI failed-job facts、分类失败并路由到正确 Skill。\n---\n"
    )
    assert 'display_name: "AI CI Failure Triage"' in metadata
    assert "CI 失败事实收集与路由" in metadata


def test_ci_triage_skill_requires_complete_facts_before_routing() -> None:
    skill = _read()
    for phrase in (
        "collect facts -> classify -> route -> report",
        "不要先猜修复",
        "job URL",
        "commit",
        "stage",
        "command",
        "exit status",
        "bounded logs",
        "environment failure",
        "build failure",
        "unit-test failure",
        "integration-test failure",
    ):
        assert phrase in skill


def test_failure_routing_reference_maps_classes_to_skills() -> None:
    reference = _read("references/failure-routing.md")
    for phrase in (
        "environment failure",
        "build failure",
        "unit-test failure",
        "integration-test failure",
        "$ai-integration-test-v2",
        "$ai-small-tdd-change",
        "$ai-workflow-harness",
        "blocked",
    ):
        assert phrase in reference
