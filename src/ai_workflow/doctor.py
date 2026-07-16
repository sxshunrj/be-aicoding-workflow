from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import sys
from typing import Literal

from ai_workflow.config import RepositoryConfig
from ai_workflow.install import CLIENT_DIRS, MANIFEST, skill_digest
from ai_workflow.wiki.repository import WikiRepository
from ai_workflow.wiki.service import WikiService


@dataclass(frozen=True, slots=True)
class DoctorCheck:
    name: str
    status: Literal["pass", "warn", "fail"]
    message: str

    def to_dict(self) -> dict[str, object]:
        return {"name": self.name, "status": self.status, "message": self.message}


@dataclass(frozen=True, slots=True)
class DoctorReport:
    checks: tuple[DoctorCheck, ...]

    @property
    def failed(self) -> tuple[DoctorCheck, ...]:
        return tuple(check for check in self.checks if check.status == "fail")

    def to_dict(self) -> dict[str, object]:
        return {
            "checks": [check.to_dict() for check in self.checks],
            "failed": [check.to_dict() for check in self.failed],
        }


def run_doctor(
    *,
    source_root: Path,
    home: Path,
    repo: Path | None = None,
    clients: tuple[str, ...] = ("codex", "claude"),
) -> DoctorReport:
    checks = [
        _python_version(),
        _cli_import(),
        _canonical_skill_layout(Path(source_root)),
        _installed_skills(Path(source_root), Path(home), clients),
        _repository_config(repo),
        _wiki_lint(repo),
    ]
    return DoctorReport(tuple(checks))


def _python_version() -> DoctorCheck:
    if sys.version_info >= (3, 11):
        return DoctorCheck("python_version", "pass", sys.version.split()[0])
    return DoctorCheck("python_version", "fail", "Python 3.11 or newer is required")


def _cli_import() -> DoctorCheck:
    try:
        import ai_workflow.cli  # noqa: F401
    except Exception as error:
        return DoctorCheck("cli_import", "fail", str(error))
    return DoctorCheck("cli_import", "pass", "ai_workflow.cli imports")


def _canonical_skill_layout(source_root: Path) -> DoctorCheck:
    if not source_root.is_dir():
        return DoctorCheck("canonical_skill_layout", "fail", "source root is missing")
    missing = []
    invalid = []
    for path in sorted(item for item in source_root.iterdir() if item.is_dir()):
        skill = path / "SKILL.md"
        if not skill.is_file():
            missing.append(path.name)
            continue
        if f"name: {path.name}" not in skill.read_text(encoding="utf-8"):
            invalid.append(path.name)
    if missing or invalid:
        return DoctorCheck(
            "canonical_skill_layout",
            "fail",
            f"missing={missing}, invalid={invalid}",
        )
    return DoctorCheck("canonical_skill_layout", "pass", "canonical skills valid")


def _installed_skills(source_root: Path, home: Path, clients: tuple[str, ...]) -> DoctorCheck:
    manifest_path = home / MANIFEST
    if not manifest_path.is_file():
        return DoctorCheck("installed_skills", "fail", "install manifest is missing")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return DoctorCheck("installed_skills", "fail", f"manifest invalid: {error}")
    items = manifest.get("items") if isinstance(manifest, dict) else None
    if not isinstance(items, list):
        return DoctorCheck("installed_skills", "fail", "manifest items are invalid")
    selected = ("codex", "claude") if clients == ("all",) else clients
    failures = []
    by_key = {
        (item.get("client"), item.get("name")): item
        for item in items
        if isinstance(item, dict)
    }
    for source in sorted(path for path in source_root.iterdir() if path.is_dir()):
        digest = skill_digest(source)
        for client in selected:
            target = home / CLIENT_DIRS[client] / source.name
            item = by_key.get((client, source.name))
            if item is None or not target.exists() or item.get("digest") != digest:
                failures.append(f"{client}:{source.name}")
    if failures:
        return DoctorCheck("installed_skills", "fail", ", ".join(failures))
    return DoctorCheck("installed_skills", "pass", "installed skill digests match")


def _repository_config(repo: Path | None) -> DoctorCheck:
    if repo is None:
        return DoctorCheck("repository_config", "warn", "repository not supplied")
    try:
        RepositoryConfig.load(Path(repo))
    except Exception as error:
        return DoctorCheck("repository_config", "fail", str(error))
    return DoctorCheck("repository_config", "pass", "repository config loads")


def _wiki_lint(repo: Path | None) -> DoctorCheck:
    if repo is None:
        return DoctorCheck("wiki_lint", "warn", "repository not supplied")
    try:
        config = RepositoryConfig.load(Path(repo))
        report = WikiService(WikiRepository(config.wiki_path)).lint()
    except Exception as error:
        return DoctorCheck("wiki_lint", "fail", str(error))
    if report.valid:
        return DoctorCheck("wiki_lint", "pass", "wiki lint clean")
    return DoctorCheck("wiki_lint", "fail", "; ".join(report.issues))
