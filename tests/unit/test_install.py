from __future__ import annotations

import json
from pathlib import Path

from ai_workflow.install import install_skills


def _skill(root: Path, name: str, body: str = "# Skill\n") -> Path:
    directory = root / name
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Use when testing {name}.\n---\n\n{body}",
        encoding="utf-8",
    )
    return directory


def test_link_install_is_idempotent_for_codex_and_claude(tmp_path: Path) -> None:
    source_root = tmp_path / "skills"
    _skill(source_root, "ai-workflow-harness")
    _skill(source_root, "ai-git-handoff")
    home = tmp_path / "home"

    first = install_skills(
        source_root=source_root,
        home=home,
        clients=("codex", "claude"),
        mode="link",
    )
    second = install_skills(
        source_root=source_root,
        home=home,
        clients=("codex", "claude"),
        mode="link",
    )

    assert first.failed == ()
    assert {item.status for item in first.items} == {"installed"}
    assert {item.status for item in second.items} == {"skipped"}
    assert (home / ".agents/skills/ai-workflow-harness").is_symlink()
    assert (home / ".claude/skills/ai-workflow-harness").is_symlink()
    manifest = json.loads((home / ".ai-workflow/install-manifest.json").read_text())
    assert manifest["schema_version"] == 1
    assert sorted(item["name"] for item in manifest["items"]) == [
        "ai-git-handoff",
        "ai-git-handoff",
        "ai-workflow-harness",
        "ai-workflow-harness",
    ]


def test_copy_mode_updates_when_source_digest_changes(tmp_path: Path) -> None:
    source_root = tmp_path / "skills"
    skill = _skill(source_root, "ai-workflow-harness", "# First\n")
    home = tmp_path / "home"

    first = install_skills(source_root=source_root, home=home, clients=("codex",), mode="copy")
    (skill / "SKILL.md").write_text(
        "---\nname: ai-workflow-harness\ndescription: Use when changed.\n---\n\n# Changed\n",
        encoding="utf-8",
    )
    second = install_skills(source_root=source_root, home=home, clients=("codex",), mode="copy")

    assert first.items[0].status == "installed"
    assert second.items[0].status == "updated"
    target = home / ".agents/skills/ai-workflow-harness"
    assert not target.is_symlink()
    assert "Changed" in (target / "SKILL.md").read_text(encoding="utf-8")


def test_reports_missing_skill_md_and_frontmatter_name_mismatch(tmp_path: Path) -> None:
    source_root = tmp_path / "skills"
    (source_root / "missing").mkdir(parents=True)
    wrong = source_root / "wrong-name"
    wrong.mkdir()
    (wrong / "SKILL.md").write_text(
        "---\nname: other-name\ndescription: Use when mismatched.\n---\n",
        encoding="utf-8",
    )

    report = install_skills(source_root=source_root, home=tmp_path / "home", clients=("codex",))

    assert sorted(item.name for item in report.failed) == ["missing", "wrong-name"]
    assert all(item.status == "failed" for item in report.failed)


def test_refuses_to_overwrite_unmanaged_targets(tmp_path: Path) -> None:
    source_root = tmp_path / "skills"
    _skill(source_root, "ai-workflow-harness")
    home = tmp_path / "home"
    target = home / ".agents/skills/ai-workflow-harness"
    target.mkdir(parents=True)
    (target / "README.md").write_text("user file", encoding="utf-8")

    report = install_skills(source_root=source_root, home=home, clients=("codex",), mode="link")

    assert report.failed[0].status == "failed"
    assert "collision" in report.failed[0].message
    assert (target / "README.md").read_text(encoding="utf-8") == "user file"


def test_repo_scope_installs_under_repository_directory(tmp_path: Path) -> None:
    source_root = tmp_path / "skills"
    _skill(source_root, "ai-workflow-harness")
    repo = tmp_path / "repo"

    report = install_skills(
        source_root=source_root,
        home=tmp_path / "home",
        clients=("codex",),
        mode="link",
        scope="repo",
        repo=repo,
    )

    assert report.failed == ()
    assert (repo / ".agents/skills/ai-workflow-harness").is_symlink()
    assert (repo / ".ai-workflow/install-manifest.json").is_file()


def test_installs_full_wave2_skill_suite_from_repository(tmp_path: Path) -> None:
    source_root = Path(__file__).resolve().parents[2] / "skills"

    report = install_skills(
        source_root=source_root,
        home=tmp_path / "home",
        clients=("codex", "claude"),
        mode="link",
    )

    assert report.failed == ()
    assert len(report.items) == 22
    assert all(item.status == "installed" for item in report.items)
    assert (tmp_path / "home/.agents/skills/ai-ci-failure-triage").is_symlink()
    assert (tmp_path / "home/.claude/skills/ai-workflow-harness-grill").is_symlink()
