from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile

from ai_workflow.errors import AppError
from ai_workflow.path_authorization import CheckpointScope
from ai_workflow.workflow.models import validate_plain_value


ZERO_OID = "0" * 40
AI_NAME = "ai-workflow"
AI_EMAIL = "ai-workflow@example.invalid"


@dataclass(frozen=True, slots=True)
class PathSnapshot:
    path: str
    kind: str
    digest: str | None

    def to_dict(self) -> dict[str, object]:
        return {"path": self.path, "kind": self.kind, "digest": self.digest}

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "PathSnapshot":
        if set(data) != {"path", "kind", "digest"}:
            raise AppError("invalid_state", "path snapshot keys are invalid")
        path = _nonblank(data["path"], "path")
        kind = _nonblank(data["kind"], "kind")
        digest = data["digest"]
        if digest is not None and not _is_sha256(digest):
            raise AppError("invalid_state", "path snapshot digest is invalid")
        if kind not in {"missing", "regular", "symlink"}:
            raise AppError("invalid_state", "path snapshot kind is invalid")
        return cls(path, kind, digest)


@dataclass(frozen=True, slots=True)
class ImplementationBaseline:
    attempt_id: str
    base_revision: str
    head_revision: str
    head_ref: str | None
    dirty_paths: tuple[str, ...]
    dirty_snapshots: tuple[PathSnapshot, ...]
    captured_at: str

    def to_dict(self) -> dict[str, object]:
        data = {
            "attempt_id": self.attempt_id,
            "base_revision": self.base_revision,
            "head_revision": self.head_revision,
            "head_ref": self.head_ref,
            "dirty_paths": list(self.dirty_paths),
            "dirty_snapshots": [item.to_dict() for item in self.dirty_snapshots],
            "captured_at": self.captured_at,
        }
        validate_plain_value(data)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "ImplementationBaseline":
        if set(data) != {
            "attempt_id",
            "base_revision",
            "head_revision",
            "head_ref",
            "dirty_paths",
            "dirty_snapshots",
            "captured_at",
        }:
            raise AppError("invalid_state", "implementation baseline keys are invalid")
        dirty_paths = data["dirty_paths"]
        dirty_snapshots = data["dirty_snapshots"]
        if not isinstance(dirty_paths, list) or not all(
            isinstance(item, str) and item for item in dirty_paths
        ):
            raise AppError("invalid_state", "baseline dirty paths are invalid")
        if not isinstance(dirty_snapshots, list) or not all(
            isinstance(item, dict) for item in dirty_snapshots
        ):
            raise AppError("invalid_state", "baseline dirty snapshots are invalid")
        head_ref = data["head_ref"]
        if head_ref is not None and (
            not isinstance(head_ref, str) or not head_ref.startswith("refs/")
        ):
            raise AppError("invalid_state", "baseline head ref is invalid")
        return cls(
            attempt_id=_nonblank(data["attempt_id"], "attempt_id"),
            base_revision=_sha(data["base_revision"], "base_revision"),
            head_revision=_sha(data["head_revision"], "head_revision"),
            head_ref=head_ref,
            dirty_paths=tuple(dirty_paths),
            dirty_snapshots=tuple(
                PathSnapshot.from_dict(item) for item in dirty_snapshots
            ),
            captured_at=_nonblank(data["captured_at"], "captured_at"),
        )


@dataclass(frozen=True, slots=True)
class CheckpointRecord:
    commit_sha: str
    tree_sha: str
    hidden_ref: str | None
    source_revision: str
    parent_commit: str
    implementation_attempt_id: str
    included_paths: tuple[str, ...]
    previous_checkpoint_sha: str | None
    created_at: str

    def to_dict(self) -> dict[str, object]:
        data = {
            "commit_sha": self.commit_sha,
            "tree_sha": self.tree_sha,
            "hidden_ref": self.hidden_ref,
            "source_revision": self.source_revision,
            "parent_commit": self.parent_commit,
            "implementation_attempt_id": self.implementation_attempt_id,
            "included_paths": list(self.included_paths),
            "previous_checkpoint_sha": self.previous_checkpoint_sha,
            "created_at": self.created_at,
        }
        validate_plain_value(data)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "CheckpointRecord":
        if set(data) != {
            "commit_sha",
            "tree_sha",
            "hidden_ref",
            "source_revision",
            "parent_commit",
            "implementation_attempt_id",
            "included_paths",
            "previous_checkpoint_sha",
            "created_at",
        }:
            raise AppError("invalid_state", "checkpoint record keys are invalid")
        hidden_ref = data["hidden_ref"]
        if hidden_ref is not None:
            hidden_ref = _checkpoint_ref(hidden_ref)
        previous = data["previous_checkpoint_sha"]
        if previous is not None:
            previous = _sha(previous, "previous_checkpoint_sha")
        paths = data["included_paths"]
        if not isinstance(paths, list) or not all(
            isinstance(item, str) and item for item in paths
        ):
            raise AppError("invalid_state", "checkpoint included paths are invalid")
        return cls(
            commit_sha=_sha(data["commit_sha"], "commit_sha"),
            tree_sha=_sha(data["tree_sha"], "tree_sha"),
            hidden_ref=hidden_ref,
            source_revision=_sha(data["source_revision"], "source_revision"),
            parent_commit=_sha(data["parent_commit"], "parent_commit"),
            implementation_attempt_id=_nonblank(
                data["implementation_attempt_id"], "implementation_attempt_id"
            ),
            included_paths=tuple(paths),
            previous_checkpoint_sha=previous,
            created_at=_nonblank(data["created_at"], "created_at"),
        )


class CheckpointService:
    def __init__(
        self,
        repo_root: Path,
        *,
        clock: Callable[[], datetime] = datetime.now,
        timeout_seconds: int = 30,
    ) -> None:
        self.repo_root = repo_root.resolve(strict=True)
        self.clock = clock
        self.timeout_seconds = timeout_seconds

    def capture_baseline(
        self,
        *,
        attempt_id: str,
        source_revision: str,
        active_checkpoint: CheckpointRecord | None,
    ) -> ImplementationBaseline:
        base = (
            active_checkpoint.commit_sha
            if active_checkpoint is not None
            else self._rev_parse(source_revision)
        )
        head = self._rev_parse("HEAD")
        head_ref = self._head_ref()
        dirty = self._changed_paths(base)
        snapshots = tuple(self._snapshot(path) for path in dirty)
        return ImplementationBaseline(
            attempt_id=attempt_id,
            base_revision=base,
            head_revision=head,
            head_ref=head_ref,
            dirty_paths=tuple(dirty),
            dirty_snapshots=snapshots,
            captured_at=self.clock().isoformat(),
        )

    def create(
        self,
        *,
        run_id: str,
        baseline: ImplementationBaseline,
        source_revision: str,
        scope: CheckpointScope,
        previous_checkpoint: CheckpointRecord | None,
        no_code_delivery: bool,
    ) -> CheckpointRecord:
        before = self._git_state()
        base = baseline.base_revision
        self._ensure_baseline_dirty_unchanged(baseline)
        candidates = [
            path
            for path in self._changed_paths(base)
            if path not in set(baseline.dirty_paths)
            and not self._ignored_workflow_path(path)
        ]
        included = tuple(sorted(scope.authorize(path) for path in candidates))
        if no_code_delivery:
            if included:
                raise AppError(
                    "checkpoint_creation_failed",
                    "no-code delivery cannot include file changes",
                )
            return CheckpointRecord(
                commit_sha=base,
                tree_sha=self._rev_parse(f"{base}^{{tree}}"),
                hidden_ref=None,
                source_revision=self._rev_parse(source_revision),
                parent_commit=base,
                implementation_attempt_id=baseline.attempt_id,
                included_paths=(),
                previous_checkpoint_sha=(
                    None
                    if previous_checkpoint is None
                    else previous_checkpoint.commit_sha
                ),
                created_at=self.clock().isoformat(),
            )
        if not included:
            raise AppError(
                "checkpoint_creation_failed",
                "implementation checkpoint has no file changes",
            )
        hidden_ref = (
            f"refs/ai-workflow/checkpoints/{run_id}/{baseline.attempt_id}"
        )
        if self._ref_exists(hidden_ref):
            raise AppError(
                "checkpoint_creation_failed",
                "checkpoint hidden ref already exists",
            )
        created_at = self.clock().isoformat()
        with tempfile.TemporaryDirectory(prefix="ai-workflow-index-") as directory:
            index = Path(directory) / "index"
            env = {
                "GIT_INDEX_FILE": str(index),
                "GIT_AUTHOR_NAME": AI_NAME,
                "GIT_AUTHOR_EMAIL": AI_EMAIL,
                "GIT_AUTHOR_DATE": created_at,
                "GIT_COMMITTER_NAME": AI_NAME,
                "GIT_COMMITTER_EMAIL": AI_EMAIL,
                "GIT_COMMITTER_DATE": created_at,
            }
            self._git("read-tree", base, env=env)
            for path in included:
                working = self.repo_root / path
                if working.exists():
                    blob = self._git(
                        "hash-object",
                        "-w",
                        "--stdin",
                        env=env,
                        input_bytes=working.read_bytes(),
                    )
                    self._git(
                        "update-index",
                        "--add",
                        "--cacheinfo",
                        "100644",
                        blob,
                        path,
                        env=env,
                    )
                else:
                    self._git("update-index", "--force-remove", "--", path, env=env)
            tree = self._git("write-tree", env=env)
            metadata = {
                "schema_version": 1,
                "run_id": run_id,
                "attempt_id": baseline.attempt_id,
                "source_revision": self._rev_parse(source_revision),
                "parent_commit": base,
                "included_paths": list(included),
                "previous_checkpoint_sha": (
                    None
                    if previous_checkpoint is None
                    else previous_checkpoint.commit_sha
                ),
                "created_at": created_at,
            }
            message = (
                "ai-workflow checkpoint\n\n"
                + json.dumps(metadata, sort_keys=True, separators=(",", ":"))
                + "\n"
            )
            commit = self._git(
                "commit-tree",
                tree,
                "-p",
                base,
                env=env,
                input_bytes=message.encode("utf-8"),
            )
            self._git(
                "update-ref",
                "--create-reflog",
                hidden_ref,
                commit,
                ZERO_OID,
            )
        after = self._git_state()
        if after != before:
            raise AppError(
                "checkpoint_creation_failed",
                "checkpoint changed user Git state",
            )
        record = CheckpointRecord(
            commit_sha=commit,
            tree_sha=tree,
            hidden_ref=hidden_ref,
            source_revision=self._rev_parse(source_revision),
            parent_commit=base,
            implementation_attempt_id=baseline.attempt_id,
            included_paths=included,
            previous_checkpoint_sha=(
                None if previous_checkpoint is None else previous_checkpoint.commit_sha
            ),
            created_at=created_at,
        )
        self.validate_record(record)
        return record

    def validate_record(self, record: CheckpointRecord) -> None:
        try:
            self._git("cat-file", "-e", f"{record.commit_sha}^{{commit}}")
            self._git("cat-file", "-e", f"{record.tree_sha}^{{tree}}")
            if record.hidden_ref is not None:
                if self._rev_parse(record.hidden_ref) != record.commit_sha:
                    raise ValueError("hidden ref mismatch")
            actual_tree = self._rev_parse(f"{record.commit_sha}^{{tree}}")
            if actual_tree != record.tree_sha:
                raise ValueError("tree mismatch")
            if record.hidden_ref is not None:
                parent = self._rev_parse(f"{record.commit_sha}^")
                if parent != record.parent_commit:
                    raise ValueError("parent mismatch")
        except (AppError, ValueError) as error:
            raise AppError(
                "checkpoint_unavailable", "checkpoint record cannot be resolved"
            ) from error

    def _changed_paths(self, base: str) -> list[str]:
        tracked = self._git("diff", "--name-only", "-z", base, "--")
        untracked = self._git("ls-files", "--others", "--exclude-standard", "-z")
        return sorted(
            set(
                path
                for output in (tracked, untracked)
                for path in output.split("\0")
                if path and not self._ignored_workflow_path(path)
            )
        )

    def _ensure_baseline_dirty_unchanged(
        self, baseline: ImplementationBaseline
    ) -> None:
        for snapshot in baseline.dirty_snapshots:
            if self._ignored_workflow_path(snapshot.path):
                continue
            if self._snapshot(snapshot.path) != snapshot:
                raise AppError(
                    "checkpoint_scope_ambiguous",
                    f"pre-existing dirty path changed: {snapshot.path}",
                )

    @staticmethod
    def _ignored_workflow_path(path: str) -> bool:
        return (
            path.startswith(".ai-workflow/runs/")
            # WeCom notify writes its dedup log under .ai-workflow/notifications/
            # at human gates; it is Helper-owned and must never count as a
            # checkpoint-visible change (previously surfaced as
            # checkpoint_scope_ambiguous after a notify).
            or path.startswith(".ai-workflow/notifications/")
            or path.startswith("artifacts/")
        )

    def _snapshot(self, path: str) -> PathSnapshot:
        target = self.repo_root / path
        try:
            metadata = target.lstat()
        except OSError:
            return PathSnapshot(path, "missing", None)
        if stat.S_ISLNK(metadata.st_mode):
            return PathSnapshot(
                path,
                "symlink",
                hashlib.sha256(os.readlink(target).encode("utf-8")).hexdigest(),
            )
        if stat.S_ISREG(metadata.st_mode):
            return PathSnapshot(
                path,
                "regular",
                hashlib.sha256(target.read_bytes()).hexdigest(),
            )
        raise AppError("path_not_authorized", f"checkpoint path is special: {path}")

    def _git_state(self) -> dict[str, object]:
        head = self._rev_parse("HEAD")
        head_ref = self._head_ref()
        branch_ref = None if head_ref is None else self._rev_parse(head_ref)
        index_path = self.repo_root / ".git" / "index"
        return {
            "head": head,
            "head_ref": head_ref,
            "branch_ref": branch_ref,
            "index": index_path.read_bytes() if index_path.exists() else b"",
        }

    def _head_ref(self) -> str | None:
        result = self._run_git("symbolic-ref", "-q", "HEAD", check=False)
        if result.returncode != 0:
            return None
        return result.stdout.decode("utf-8").strip()

    def _ref_exists(self, ref: str) -> bool:
        return self._run_git("show-ref", "--verify", "--quiet", ref, check=False).returncode == 0

    def _rev_parse(self, revision: str) -> str:
        return self._git("rev-parse", revision)

    def _git(
        self,
        *args: str,
        env: dict[str, str] | None = None,
        input_bytes: bytes | None = None,
    ) -> str:
        result = self._run_git(*args, env=env, input_bytes=input_bytes)
        return result.stdout.decode("utf-8").strip()

    def _run_git(
        self,
        *args: str,
        env: dict[str, str] | None = None,
        input_bytes: bytes | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[bytes]:
        merged = os.environ.copy()
        if env is not None:
            merged.update(env)
        result = subprocess.run(
            ["git", *args],
            cwd=self.repo_root,
            input=input_bytes,
            capture_output=True,
            timeout=self.timeout_seconds,
            env=merged,
        )
        if check and result.returncode != 0:
            raise AppError(
                "checkpoint_creation_failed",
                f"git {' '.join(args)} failed with exit {result.returncode}",
                details={
                    "argv": ["git", *args],
                    "exit_status": result.returncode,
                    "stdout": result.stdout.decode("utf-8", errors="replace")[:2000],
                    "stderr": result.stderr.decode("utf-8", errors="replace")[:2000],
                },
            )
        return result


def _nonblank(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AppError("invalid_state", f"{name} must be a non-empty string")
    return value


def _sha(value: object, name: str) -> str:
    text = _nonblank(value, name)
    if len(text) != 40 or any(character not in "0123456789abcdef" for character in text):
        raise AppError("invalid_state", f"{name} must be a git SHA")
    return text


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _checkpoint_ref(value: object) -> str:
    text = _nonblank(value, "hidden_ref")
    if not text.startswith("refs/ai-workflow/checkpoints/") or ".." in text:
        raise AppError("invalid_state", "checkpoint hidden ref is invalid")
    return text
