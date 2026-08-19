from pathlib import Path


SKILL_DIRS = {
    "harness": Path("skills/ai-workflow-harness"),
    "grill": Path("skills/ai-workflow-harness-grill"),
    "git_handoff": Path("skills/ai-git-handoff"),
    "governance": Path("skills/ai-knowledge-governance"),
}


def _read(skill_key: str, relative: str = "SKILL.md") -> str:
    return (SKILL_DIRS[skill_key] / relative).read_text(encoding="utf-8")


def test_harness_skill_references_wecom_notify() -> None:
    skill = _read("harness")
    assert "ai-workflow wecom notify" in skill
    assert "Review Gate" in skill and "wecom notify" in skill


def test_harness_review_notify_passes_phase_and_blocked_is_helper_enforced() -> None:
    """Regression guard: review notify must pass ``--phase`` (per-phase dedup
    keys never collide), while blocked notify is Helper-mechanical (``workflow
    block`` auto-pushes) so it must not rely on the LLM calling it."""
    skill = _read("harness")
    assert "--gate review --phase <phase>" in skill
    assert "--gate blocked" not in skill
    assert "机械保证" in skill


def test_harness_terminal_completion_notify_present() -> None:
    """Terminal completion is a mandatory human gate: the harness must notify
    the team when waiting for terminal acceptance (completed/aborted)."""
    skill = _read("harness")
    assert "--gate terminal" in skill
    assert "completed/aborted" in skill


def test_grill_review_notify_passes_phase_and_blocked_is_helper_enforced() -> None:
    """The grill harness variant has the same human gates: review notifies with
    ``--phase``, blocked is Helper-mechanical (``workflow block`` auto-pushes)."""
    skill = _read("grill")
    assert "--gate review --phase <phase>" in skill
    assert "--gate blocked" not in skill
    assert "机械保证" in skill


def test_grill_terminal_notify_present() -> None:
    skill = _read("grill")
    assert "--gate terminal" in skill
    assert "completed/aborted" in skill


def test_git_handoff_skill_references_wecom_notify() -> None:
    skill = _read("git_handoff")
    assert "ai-workflow wecom notify" in skill


def test_governance_skill_references_wecom_notify() -> None:
    skill = _read("governance")
    assert "ai-workflow wecom notify" in skill


def test_harness_wecom_notify_reference_exists() -> None:
    ref = _read("harness", "references/wecom-notify.md")
    for phrase in (
        "ai-workflow wecom notify",
        "--gate",
        "--run-id",
        "dry-run",
        "dedup",
        "不影响主流程",
        # phase is mandatory for review/blocked so per-phase dedup keys never
        # collide; only sent==true counts as "已通知团队".
        "必须传 `--phase",
        "sent == true",
        # terminal gate covers run-completion acceptance.
        "git_handoff|terminal",
    ):
        assert phrase in ref
