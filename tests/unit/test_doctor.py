from __future__ import annotations

from pathlib import Path

from ai_workflow.doctor import run_doctor
from ai_workflow.install import install_skills


def _skill(root: Path, name: str) -> None:
    directory = root / name
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Use when testing {name}.\n---\n\n# {name}\n",
        encoding="utf-8",
    )


def _repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    (repo / ".ai-workflow.yaml").write_text(
        "repository: demo\nwiki_path: wiki\n", encoding="utf-8"
    )
    for name in ("approved", "candidates", "archive"):
        (repo / "wiki" / name).mkdir(parents=True, exist_ok=True)
    (repo / "wiki" / "taxonomy.yaml").write_text(
        "schema_version: 1\n"
        "types: [rule, decision, pattern, pitfall, procedure, diagnostic, workflow]\n"
        "phases: [spec, plan, implement, verify]\n",
        encoding="utf-8",
    )
    return repo


def test_doctor_passes_for_installed_skills_repo_config_and_wiki(tmp_path: Path) -> None:
    source_root = tmp_path / "skills"
    _skill(source_root, "ai-workflow-harness")
    _skill(source_root, "ai-git-handoff")
    home = tmp_path / "home"
    install_skills(source_root=source_root, home=home, clients=("codex",))
    repo = _repo(tmp_path)

    report = run_doctor(source_root=source_root, home=home, repo=repo, clients=("codex",))

    assert report.failed == ()
    assert {check.name for check in report.checks} >= {
        "python_version",
        "cli_import",
        "canonical_skill_layout",
        "installed_skills",
        "repository_config",
        "wiki_lint",
    }


def test_doctor_fails_for_missing_installed_skill(tmp_path: Path) -> None:
    source_root = tmp_path / "skills"
    _skill(source_root, "ai-workflow-harness")

    report = run_doctor(source_root=source_root, home=tmp_path / "home", clients=("codex",))

    assert report.failed
    assert any(check.name == "installed_skills" for check in report.failed)


def test_doctor_warns_when_repo_not_supplied(tmp_path: Path) -> None:
    source_root = tmp_path / "skills"
    _skill(source_root, "ai-workflow-harness")
    home = tmp_path / "home"
    install_skills(source_root=source_root, home=home, clients=("codex",))

    report = run_doctor(source_root=source_root, home=home, clients=("codex",))

    assert report.failed == ()
    assert any(check.name == "repository_config" and check.status == "warn" for check in report.checks)
