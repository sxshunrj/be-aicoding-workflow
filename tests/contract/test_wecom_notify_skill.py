from pathlib import Path


SKILL_DIRS = {
    "harness": Path("skills/ai-workflow-harness"),
    "grill": Path("skills/ai-workflow-harness-grill"),
    "git_handoff": Path("skills/ai-git-handoff"),
    "governance": Path("skills/ai-knowledge-governance"),
}


def _read(skill_key: str, relative: str = "SKILL.md") -> str:
    return (SKILL_DIRS[skill_key] / relative).read_text(encoding="utf-8")


def test_harness_skill_delegates_notify_to_helper() -> None:
    """review/blocked/terminal notifications are Helper-mechanical: the harness
    skill must say the ``workflow`` commands auto-push them and must not rely on
    the LLM calling ``wecom notify`` directly (that path could be skipped)."""
    skill = _read("harness")
    assert "workflow review` 命令会自动推送" in skill
    assert "workflow block` 命令会自动推送" in skill
    assert "workflow transition` / `workflow abort` 命令会自动推送" in skill
    assert "机械保证" in skill


def test_harness_skill_has_no_llm_gate_notify_calls() -> None:
    skill = _read("harness")
    assert "--gate review" not in skill
    assert "--gate blocked" not in skill
    assert "--gate terminal" not in skill


def test_grill_skill_delegates_notify_to_helper() -> None:
    skill = _read("grill")
    assert "workflow review` 命令会自动推送" in skill
    assert "workflow block` 命令会自动推送" in skill
    assert "workflow transition` / `workflow abort` 命令会自动推送" in skill
    assert "--gate review" not in skill
    assert "--gate terminal" not in skill
    # EXCEPTION: grill's plan phase is a pure Q&A loop with NO Helper command to
    # carry a mechanical notify — blocking questions wait for human answers
    # across sessions. That one wait must use a template-driven `--gate blocked`
    # (with --phase plan so it never collides with a real workflow-block dedup).
    assert "--gate blocked --phase plan" in skill
    assert "blocking questions" in skill
    # every other blocked/terminal gate stays Helper-mechanical
    assert "自动推送" in skill


def test_git_handoff_skill_references_wecom_notify() -> None:
    skill = _read("git_handoff")
    assert "ai-workflow wecom notify" in skill
    # the notify call must carry the correct gate so the team knows WHAT needs
    # a human; and it must be non-blocking so a notify failure never stalls the
    # git handoff
    assert "--gate git_handoff" in skill
    assert "失败仅写 warning，不影响主流程" in skill


def test_governance_skill_references_wecom_notify() -> None:
    skill = _read("governance")
    assert "ai-workflow wecom notify" in skill
    assert "--gate governance" in skill
    assert "失败仅写 warning，不影响主流程" in skill


def test_harness_wecom_notify_reference_exists() -> None:
    ref = _read("harness", "references/wecom-notify.md")
    for phrase in (
        "ai-workflow wecom notify",
        "--gate",
        "--run-id",
        "dry-run",
        "dedup",
        "不影响主流程",
        # review/blocked/terminal are Helper-mechanical; only sent==true counts
        # as "已通知团队".
        "自动推送",
        "机械保证",
        "sent == true",
        # gate list covers the five gates.
        "git_handoff|terminal",
    ):
        assert phrase in ref
