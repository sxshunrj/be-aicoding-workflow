from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Literal


CLIENT_DIRS = {
    "codex": Path(".agents/skills"),
    "claude": Path(".claude/skills"),
}
MANIFEST = ".ai-workflow/install-manifest.json"
InstallMode = Literal["auto", "link", "copy"]
EffectiveInstallMode = Literal["link", "copy"]


@dataclass(frozen=True, slots=True)
class InstallItem:
    name: str
    client: str
    source: str
    target: str
    digest: str
    status: Literal["installed", "updated", "skipped", "failed"]
    message: str

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "client": self.client,
            "source": self.source,
            "target": self.target,
            "digest": self.digest,
            "status": self.status,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class InstallReport:
    items: tuple[InstallItem, ...]
    manifest_path: str

    @property
    def failed(self) -> tuple[InstallItem, ...]:
        return tuple(item for item in self.items if item.status == "failed")

    def to_dict(self) -> dict[str, object]:
        return {
            "items": [item.to_dict() for item in self.items],
            "manifest_path": self.manifest_path,
            "failed": [item.to_dict() for item in self.failed],
        }


def install_skills(
    *,
    source_root: Path,
    home: Path,
    clients: tuple[str, ...] = ("codex", "claude"),
    mode: InstallMode = "auto",
    scope: Literal["user", "repo"] = "user",
    repo: Path | None = None,
) -> InstallReport:
    if mode not in {"auto", "link", "copy"}:
        raise ValueError("mode must be auto, link, or copy")
    effective_mode = default_install_mode() if mode == "auto" else mode
    roots = _install_roots(home, clients, scope=scope, repo=repo)
    source_root = Path(source_root).resolve()
    manifest_path = _manifest_root(home, scope=scope, repo=repo) / MANIFEST
    previous = _read_manifest(manifest_path)
    items: list[InstallItem] = []
    for source in sorted(path for path in source_root.iterdir() if path.is_dir()):
        name = source.name
        try:
            _validate_skill_source(source)
            digest = skill_digest(source)
        except Exception as error:
            for client in roots:
                items.append(
                    InstallItem(
                        name,
                        client,
                        str(source),
                        str(roots[client] / name),
                        "",
                        "failed",
                        str(error),
                    )
                )
            continue
        for client, root in roots.items():
            target = root / name
            try:
                status, message = _install_one(
                    name=name,
                    client=client,
                    source=source,
                    target=target,
                    digest=digest,
                    mode=effective_mode,
                    previous=previous,
                )
            except OSError as error:
                status, message = "failed", str(error)
            items.append(
                InstallItem(
                    name,
                    client,
                    str(source),
                    str(target),
                    digest,
                    status,
                    message,
                )
            )
    report = InstallReport(tuple(items), str(manifest_path))
    _write_manifest(manifest_path, report)
    return report


def default_install_mode(platform_name: str | None = None) -> EffectiveInstallMode:
    platform_name = os.name if platform_name is None else platform_name
    return "copy" if platform_name == "nt" else "link"


def skill_digest(source: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in Path(source).rglob("*") if p.is_file()):
        relative = path.relative_to(source).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _install_roots(
    home: Path,
    clients: tuple[str, ...],
    *,
    scope: str,
    repo: Path | None,
) -> dict[str, Path]:
    selected = ("codex", "claude") if clients == ("all",) else clients
    roots: dict[str, Path] = {}
    base = Path(home) if scope == "user" else _repo_required(repo)
    for client in selected:
        if client not in CLIENT_DIRS:
            raise ValueError(f"unsupported client: {client}")
        roots[client] = base / CLIENT_DIRS[client]
    return roots


def _manifest_root(home: Path, *, scope: str, repo: Path | None) -> Path:
    return Path(home) if scope == "user" else _repo_required(repo)


def _repo_required(repo: Path | None) -> Path:
    if repo is None:
        raise ValueError("repo scope requires repo")
    return Path(repo)


def _install_one(
    *,
    name: str,
    client: str,
    source: Path,
    target: Path,
    digest: str,
    mode: EffectiveInstallMode,
    previous: dict[tuple[str, str], dict[str, object]],
) -> tuple[Literal["installed", "updated", "skipped", "failed"], str]:
    prior = previous.get((client, name))
    if target.exists() or target.is_symlink():
        if _target_matches(target, source, digest, mode, prior):
            return "skipped", "already installed"
        if not _is_managed_target(target, prior):
            return "failed", "collision with unmanaged target"
        _remove_target(target)
        status: Literal["installed", "updated"] = "updated"
    else:
        status = "installed"
    target.parent.mkdir(parents=True, exist_ok=True)
    if mode == "link":
        target.symlink_to(source, target_is_directory=True)
    else:
        shutil.copytree(source, target)
    return status, mode


def _target_matches(
    target: Path,
    source: Path,
    digest: str,
    mode: EffectiveInstallMode,
    prior: dict[str, object] | None,
) -> bool:
    if prior is None or prior.get("digest") != digest:
        return False
    if mode == "link":
        return target.is_symlink() and target.resolve() == source.resolve()
    return target.is_dir() and not target.is_symlink() and skill_digest(target) == digest


def _is_managed_target(target: Path, prior: dict[str, object] | None) -> bool:
    if target.is_symlink():
        return True
    return prior is not None and prior.get("target") == str(target)


def _remove_target(target: Path) -> None:
    if target.is_symlink() or target.is_file():
        target.unlink()
    else:
        shutil.rmtree(target)


def _validate_skill_source(source: Path) -> None:
    skill = source / "SKILL.md"
    if not skill.is_file():
        raise ValueError("missing SKILL.md")
    declared = _frontmatter_name(skill)
    if declared != source.name:
        raise ValueError("frontmatter name does not match directory")


def _frontmatter_name(path: Path) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != "---":
        raise ValueError("SKILL.md must begin with frontmatter")
    for line in lines[1:]:
        if line == "---":
            break
        if line.startswith("name:"):
            return line.split(":", 1)[1].strip()
    raise ValueError("frontmatter name is missing")


def _read_manifest(path: Path) -> dict[tuple[str, str], dict[str, object]]:
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        return {}
    items = raw.get("items")
    if not isinstance(items, list):
        return {}
    result: dict[tuple[str, str], dict[str, object]] = {}
    for item in items:
        if isinstance(item, dict) and isinstance(item.get("name"), str) and isinstance(item.get("client"), str):
            result[(item["client"], item["name"])] = item
    return result


def _write_manifest(path: Path, report: InstallReport) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "items": [item.to_dict() for item in report.items],
    }
    descriptor, name = tempfile.mkstemp(prefix=".install-manifest.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)
