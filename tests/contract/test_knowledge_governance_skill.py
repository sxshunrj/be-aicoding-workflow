from pathlib import Path


SKILL_DIR = Path("skills/ai-knowledge-governance")


def _read(relative: str = "SKILL.md") -> str:
    return (SKILL_DIR / relative).read_text(encoding="utf-8")


def test_governance_skill_frontmatter_and_sequence_are_canonical() -> None:
    skill = _read()

    assert skill.startswith(
        "---\nname: ai-knowledge-governance\n"
        "description: Use when reviewing ai-workflow candidate knowledge for human promotion, rejection, or leaving it unchanged.\n"
        "---\n"
    )
    assert (
        "wiki review -> inspect candidate evidence, scope, reuse reason, conflicts, expiry, "
        "and related approved entries -> show digest and material differences -> human choice "
        "-> execute exactly one digest-protected lifecycle command -> report result"
    ) in skill
    for required in (
        "promote",
        "reject",
        "leave candidate unchanged",
        "No choice may default to promote",
        "expected-digest",
        "wiki promote",
        "wiki reject",
    ):
        assert required in skill


def test_governance_checklist_requires_review_controls() -> None:
    checklist = _read("references/review-checklist.md")

    for required in (
        "source-run evidence",
        "scope",
        "owners",
        "review date",
        "duplicate/conflict analysis",
        "supersession consistency",
        "secret/PII screening",
        "current digest",
    ):
        assert required in checklist


def test_governance_skill_has_ui_metadata_and_checklist_link() -> None:
    skill = _read()
    metadata = _read("agents/openai.yaml")

    assert "](references/review-checklist.md)" in skill
    assert "display_name" in metadata
    assert "$ai-knowledge-governance" in metadata
