from __future__ import annotations

from dataclasses import fields
import os
from pathlib import Path
import tempfile

import yaml

from ai_workflow.errors import AppError
from ai_workflow.wiki.models import (
    KnowledgeEntry,
    KnowledgeScope,
    KnowledgeStatus,
    KnowledgeType,
    validate_entry_id,
)


DIRECTORY = {
    KnowledgeStatus.CANDIDATE: "candidates",
    KnowledgeStatus.APPROVED: "approved",
    KnowledgeStatus.ARCHIVED: "archive",
    KnowledgeStatus.SUPERSEDED: "archive",
}
LIFECYCLE_DIRECTORIES = ("approved", "candidates", "archive")


class WikiRepository:
    def __init__(self, root: Path, *, validate_layout: bool = True) -> None:
        supplied = Path(root)
        if supplied.is_symlink():
            raise AppError("wiki_invalid", "wiki root must not be a symbolic link")
        self.root = supplied.resolve()
        if validate_layout:
            self.validate_layout()

    def validate_layout(self) -> None:
        if not self.root.is_dir():
            raise AppError("wiki_invalid", f"wiki root is not an existing directory: {self.root}")
        for name in LIFECYCLE_DIRECTORIES:
            path = self.root / name
            if path.is_symlink() or not path.is_dir():
                raise AppError("wiki_invalid", f"lifecycle directory is missing or unsafe: {name}")
        taxonomy = self.root / "taxonomy.yaml"
        if taxonomy.is_symlink() or not taxonomy.is_file():
            raise AppError("wiki_invalid", "taxonomy.yaml is missing or unsafe")

    def taxonomy(self) -> tuple[set[str], set[str]]:
        self.validate_layout()
        path = self.root / "taxonomy.yaml"
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as error:
            raise AppError("wiki_invalid", f"taxonomy.yaml is invalid: {error}") from error
        if not isinstance(loaded, dict) or loaded.get("schema_version") != 1:
            raise AppError("wiki_invalid", "taxonomy.yaml must be a schema_version 1 mapping")
        types = _taxonomy_values(loaded.get("types"), "types")
        unknown_types = types - {item.value for item in KnowledgeType}
        if unknown_types:
            raise AppError("wiki_invalid", f"taxonomy contains unknown type: {sorted(unknown_types)[0]}")
        return types, _taxonomy_values(loaded.get("phases"), "phases")

    def paths(self) -> list[Path]:
        self.validate_layout()
        result: list[Path] = []
        for name in LIFECYCLE_DIRECTORIES:
            directory = self.root / name
            for path in directory.iterdir():
                if path.suffix != ".md":
                    continue
                self._safe_file(path, must_exist=True)
                result.append(path)
        return sorted(result)

    def list(self, status: KnowledgeStatus | str) -> list[KnowledgeEntry]:
        wanted = _status(status)
        entries = [self.read(path) for path in self.paths() if path.parent.name == DIRECTORY[wanted]]
        return sorted((entry for entry in entries if entry.status is wanted), key=lambda entry: entry.id)

    def read(self, path: Path) -> KnowledgeEntry:
        safe = self._safe_file(Path(path), must_exist=True)
        allowed_types, allowed_phases = self.taxonomy()
        try:
            content = safe.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise AppError("wiki_invalid", f"cannot read {safe}: {error}") from error
        metadata, body = _front_matter(content)
        return KnowledgeEntry.from_parts(
            metadata, body, allowed_types=allowed_types, allowed_phases=allowed_phases
        )

    def serialize(self, entry: KnowledgeEntry) -> str:
        validate_entry_id(entry.id)
        return _serialize(entry)

    def write_candidate(self, entry: KnowledgeEntry) -> Path:
        self.validate_layout()
        validate_entry_id(entry.id)
        allowed_types, allowed_phases = self.taxonomy()
        if entry.type.value not in allowed_types or set(entry.scope.phases) - allowed_phases:
            raise AppError("wiki_invalid", "knowledge entry is not allowed by taxonomy")
        if entry.status is not KnowledgeStatus.CANDIDATE:
            raise AppError("wiki_invalid", "only candidate knowledge can be written")
        target = self._safe_file(self.root / "candidates" / f"{entry.id}.md")
        if os.path.lexists(target):
            raise AppError("wiki_conflict", f"knowledge entry already exists: {entry.id}")
        data = self.serialize(entry)
        temporary: Path | None = None
        placeholder_created = False
        try:
            descriptor, name = tempfile.mkstemp(prefix=f".{entry.id}.", suffix=".tmp", dir=target.parent)
            temporary = Path(name)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            placeholder = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            os.close(placeholder)
            placeholder_created = True
            os.replace(temporary, target)
            return target
        except OSError as error:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            if placeholder_created:
                target.unlink(missing_ok=True)
            raise AppError("wiki_invalid", f"cannot write knowledge entry: {error}") from error

    def move(
        self,
        entry_id: str,
        source: KnowledgeStatus | str,
        target: KnowledgeStatus | str,
    ) -> Path:
        self.validate_layout()
        validate_entry_id(entry_id)
        source_status, target_status = _status(source), _status(target)
        source_path = self._safe_file(
            self.root / DIRECTORY[source_status] / f"{entry_id}.md", must_exist=True
        )
        target_path = self._safe_file(self.root / DIRECTORY[target_status] / f"{entry_id}.md")
        if source_path == target_path or os.path.lexists(target_path):
            raise AppError("wiki_conflict", f"target knowledge entry already exists: {entry_id}")
        entry = self.read(source_path)
        if entry.status is not target_status:
            raise AppError("wiki_invalid", "entry status does not match target lifecycle")
        linked = False
        try:
            os.link(source_path, target_path)
            linked = True
            source_path.unlink()
        except OSError as error:
            if linked:
                target_path.unlink(missing_ok=True)
            raise AppError("wiki_invalid", f"cannot move knowledge entry: {error}") from error
        return target_path

    def _safe_file(self, path: Path, *, must_exist: bool = False) -> Path:
        if path.is_symlink():
            raise AppError("wiki_invalid", f"symbolic link is not allowed: {path}")
        resolved = path.resolve(strict=False)
        try:
            resolved.relative_to(self.root)
        except ValueError as error:
            raise AppError("wiki_invalid", f"path escapes wiki root: {path}") from error
        if must_exist and (not resolved.is_file() or resolved.is_symlink()):
            raise AppError("wiki_not_found", f"knowledge entry not found: {path.name}")
        if resolved.parent.name not in LIFECYCLE_DIRECTORIES:
            raise AppError("wiki_invalid", f"path is outside a lifecycle directory: {path}")
        return resolved


def _status(value: KnowledgeStatus | str) -> KnowledgeStatus:
    try:
        return KnowledgeStatus(value)
    except ValueError as error:
        raise AppError("wiki_invalid", f"unknown knowledge status: {value}") from error


def _taxonomy_values(value: object, name: str) -> set[str]:
    if not isinstance(value, list) or not value or not all(isinstance(item, str) and item.strip() for item in value):
        raise AppError("wiki_invalid", f"taxonomy {name} must be a non-empty string list")
    normalized = [item.strip() for item in value]
    if len(set(normalized)) != len(normalized):
        raise AppError("wiki_invalid", f"taxonomy {name} must contain unique values")
    return set(normalized)


def _front_matter(content: str) -> tuple[dict[str, object], str]:
    lines = content.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---" or lines[0] not in {"---\n", "---\r\n"}:
        raise AppError("wiki_invalid", "Markdown file must begin with YAML front matter")
    closing = next((index for index, line in enumerate(lines[1:], 1) if line.rstrip("\r\n") == "---" and line in {"---\n", "---\r\n", "---"}), None)
    if closing is None:
        raise AppError("wiki_invalid", "Markdown file is missing the closing front matter delimiter")
    try:
        loaded = yaml.safe_load("".join(lines[1:closing]))
    except yaml.YAMLError as error:
        raise AppError("wiki_invalid", "front matter YAML is invalid") from error
    if not isinstance(loaded, dict):
        raise AppError("wiki_invalid", "front matter must be a mapping")
    return loaded, "".join(lines[closing + 1 :])


def _serialize(entry: KnowledgeEntry) -> str:
    metadata = {field.name: getattr(entry, field.name) for field in fields(entry) if field.name != "body"}
    metadata["type"], metadata["status"] = entry.type.value, entry.status.value
    metadata["scope"] = {field.name: list(getattr(entry.scope, field.name)) for field in fields(KnowledgeScope)}
    for name in ("tags", "owners", "reviewers", "sources", "supersedes", "conflicts_with"):
        metadata[name] = list(metadata[name])
    return f"---\n{yaml.safe_dump(metadata, sort_keys=False)}---\n{entry.body}\n"
