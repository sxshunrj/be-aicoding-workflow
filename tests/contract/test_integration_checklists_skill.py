from pathlib import Path


SKILL_DIR = Path("skills/ai-integration-test-checklists")


def _read(relative: str = "SKILL.md") -> str:
    return (SKILL_DIR / relative).read_text(encoding="utf-8")


def test_checklists_frontmatter_and_metadata_are_canonical() -> None:
    skill = _read()
    metadata = _read("agents/openai.yaml")
    assert skill.startswith(
        "---\nname: ai-integration-test-checklists\n"
        "description: Use when 用户要求把需求、设计、PRD、diff 或实现说明转换成 integration-test checklist。\n---\n"
    )
    assert 'display_name: "AI Integration Test Checklists"' in metadata
    assert "集成测试 checklist" in metadata


def test_checklists_skill_requires_evidence_mapping_and_gap_analysis() -> None:
    skill = _read()
    for phrase in (
        "evidence-mapped checklist",
        "需求来源",
        "代码 diff",
        "已有测试资产",
        "覆盖项",
        "缺口",
        "风险",
        "不要生成泛泛 checklist",
    ):
        assert phrase in skill


def test_checklist_schema_reference_defines_required_sections() -> None:
    schema = _read("references/checklist-schema.md")
    for phrase in (
        "Scope",
        "Evidence Map",
        "Checklist Items",
        "Gap Analysis",
        "Verification Commands",
        "每个 checklist item 必须指向 evidence",
    ):
        assert phrase in schema
