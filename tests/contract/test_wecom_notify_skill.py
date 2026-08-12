from pathlib import Path


SKILL_DIRS = {
    "harness": Path("skills/ai-workflow-harness"),
    "git_handoff": Path("skills/ai-git-handoff"),
    "governance": Path("skills/ai-knowledge-governance"),
}


def _read(skill_key: str, relative: str = "SKILL.md") -> str:
    return (SKILL_DIRS[skill_key] / relative).read_text(encoding="utf-8")


def test_harness_skill_references_wecom_notify() -> None:
    skill = _read("harness")
    assert "ai-workflow wecom notify" in skill
    assert "Review Gate" in skill and "wecom notify" in skill


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
    ):
        assert phrase in ref
