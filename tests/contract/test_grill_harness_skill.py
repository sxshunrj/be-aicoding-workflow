from pathlib import Path


SKILL_DIR = Path("skills/ai-workflow-harness-grill")


def _read(relative: str = "SKILL.md") -> str:
    return (SKILL_DIR / relative).read_text(encoding="utf-8")


def test_grill_frontmatter_and_display_metadata_are_canonical() -> None:
    skill = _read()
    metadata = _read("agents/openai.yaml")
    assert skill.startswith(
        "---\nname: ai-workflow-harness-grill\n"
        "description: Use when 用户显式要求 PRD-driven plan/implement/verify workflow，"
        "或要求 ai-workflow grill harness。\n---\n"
    )
    assert 'display_name: "AI Workflow Harness Grill"' in metadata
    assert "交互式 PRD 驱动" in metadata


def test_grill_skill_defines_prd_driven_three_phase_loop() -> None:
    skill = _read()
    for phrase in (
        "plan -> implement -> verify",
        "一次只问一个问题",
        "plan phase 由主 Agent 交互式拥有",
        "implement 和 verify 仍然 child-backed",
        "PRD issue identifier 是内容标识，不是 dynamic run-graph node",
        "不得直接编辑 `.ai-workflow/runs/**`",
        "plan 不派 child",
        "workflow-owned PRD",
        "stage-owned",
        "Review Gate",
        "blocked 不自动恢复",
        "terminal Git handoff",
    ):
        assert phrase in skill
    assert len(skill.splitlines()) >= 90


def test_grill_references_cover_prd_loop_and_dispatch_boundaries() -> None:
    prd = _read("references/prd-loop.md")
    dispatch = _read("references/dispatch.md")
    for phrase in (
        "acceptance criteria",
        "non-goals",
        "open questions",
        "PRD artifact",
        "一次只问一个问题",
        "resolved questions",
        "blocking questions",
        "stage-owned",
        "不得直接构造 ChildResult",
    ):
        assert phrase in prd
    for phrase in (
        "prompt_file",
        "ChildResult",
        "barrier",
        "stage",
        "finalize",
        "implement",
        "verify",
        "Review Gate",
        "checkpoint",
        "dispatch 不追加隐藏上下文",
    ):
        assert phrase in dispatch
    assert len(prd.splitlines()) >= 80
    assert len(dispatch.splitlines()) >= 70
