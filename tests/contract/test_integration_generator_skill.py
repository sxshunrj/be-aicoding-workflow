from pathlib import Path


SKILL_DIR = Path("skills/ai-integration-test-generator")


def _read(relative: str = "SKILL.md") -> str:
    return (SKILL_DIR / relative).read_text(encoding="utf-8")


def test_generator_frontmatter_and_metadata_are_canonical() -> None:
    skill = _read()
    metadata = _read("agents/openai.yaml")
    assert skill.startswith(
        "---\nname: ai-integration-test-generator\n"
        "description: Use when 用户要求基于 repository adapter 生成或更新 integration-test assets。\n---\n"
    )
    assert 'display_name: "AI Integration Test Generator"' in metadata
    assert "生成或更新集成测试资产" in metadata


def test_generator_skill_requires_repository_adapter_and_reviewable_outputs() -> None:
    skill = _read()
    for phrase in (
        "repository adapter",
        "generated_test_destinations",
        "source_paths",
        "test_paths",
        "report_paths",
        "只写被 adapter 授权的测试路径",
        "不得修改生产代码",
        "输出变更摘要和验证命令",
    ):
        assert phrase in skill


def test_generator_skill_requires_mechanical_path_authorization() -> None:
    skill = _read()
    reference = _read("references/repository-adapter.md")
    combined = f"{skill}\n{reference}"

    for phrase in (
        "ai-workflow config authorize-path --repo REPO --kind input --path PATH",
        "ai-workflow config authorize-path --repo REPO --kind generated-test --path PATH",
        "ai-workflow config authorize-path --repo REPO --kind report --path PATH",
        "path_not_authorized",
        "fail closed",
    ):
        assert phrase in combined


def test_repository_adapter_reference_lists_required_fields() -> None:
    reference = _read("references/repository-adapter.md")
    for phrase in (
        "source_paths",
        "test_paths",
        "generated_test_destinations",
        "report_paths",
        "commands.integration_test",
        "protected_paths",
    ):
        assert phrase in reference
