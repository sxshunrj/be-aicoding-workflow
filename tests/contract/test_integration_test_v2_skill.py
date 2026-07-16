from pathlib import Path


SKILL_DIR = Path("skills/ai-integration-test-v2")


def _read(relative: str = "SKILL.md") -> str:
    return (SKILL_DIR / relative).read_text(encoding="utf-8")


def test_integration_v2_frontmatter_and_metadata_are_canonical() -> None:
    skill = _read()
    metadata = _read("agents/openai.yaml")
    assert skill.startswith(
        "---\nname: ai-integration-test-v2\n"
        "description: Use when 用户要求执行、诊断或收敛 integration tests，"
        "且不能让 case 迎合错误代码。\n---\n"
    )
    assert 'display_name: "AI Integration Test V2"' in metadata
    assert "执行、诊断和收敛集成测试" in metadata


def test_integration_v2_skill_enforces_convergence_discipline() -> None:
    skill = _read()
    for phrase in (
        "execute -> diagnose -> classify -> fix -> rerun",
        "不能让 case 迎合错误代码",
        "先定位失败归因",
        "implementation bug",
        "test asset bug",
        "environment issue",
        "mock/fixture drift",
        "每次只改一个归因",
    ):
        assert phrase in skill


def test_convergence_reference_lists_failure_classes_and_outputs() -> None:
    reference = _read("references/convergence.md")
    for phrase in (
        "Failure classes",
        "implementation bug",
        "test asset bug",
        "environment issue",
        "mock/fixture drift",
        "Rerun evidence",
        "Do not update expected output to match broken behavior",
    ):
        assert phrase in reference
