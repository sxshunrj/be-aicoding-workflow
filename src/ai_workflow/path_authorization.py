from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath
import stat
from typing import Literal

from ai_workflow.config import RepositoryConfig
from ai_workflow.errors import AppError


PathKind = Literal["input", "generated-test", "report"]

_INTERNAL_DENY_PATTERNS = (
    ".git",
    ".git/**",
    ".ai-workflow",
    ".ai-workflow/**",
    ".ai-workflow.yaml",
)
_FALLBACK_INPUT_DENY_PATTERNS = (
    "artifacts",
    "artifacts/**",
)


@dataclass(frozen=True, slots=True)
class CheckpointScope:
    repo_root: Path
    protected_patterns: tuple[str, ...]
    report_patterns: tuple[str, ...]

    def authorize(self, path: str) -> str:
        return _authorize_checkpoint_candidate(
            self.repo_root,
            path,
            protected_patterns=self.protected_patterns,
            report_patterns=self.report_patterns,
        )


class RepositoryPathAuthorizer:
    def __init__(self, repo_root: Path, config: RepositoryConfig) -> None:
        self.repo_root = repo_root.resolve(strict=True)
        self.config = config

    def authorize(
        self,
        kind: PathKind,
        path: str,
        *,
        helper_owned_report_paths: tuple[str, ...] = (),
    ) -> str:
        normalized = _normalize(path)
        self._require_inside_repository(normalized)
        self._require_not_denied(normalized)
        self._require_allowed_for_kind(
            kind,
            normalized,
            helper_owned_report_paths=helper_owned_report_paths,
        )
        return normalized

    def allowed_input_paths(
        self,
        *,
        helper_owned_input_paths: tuple[str, ...] = (),
    ) -> tuple[str, ...]:
        candidates = self._configured_or_fallback_input_candidates()
        authorized = [self.authorize("input", path) for path in candidates]
        authorized.extend(
            self._authorize_helper_owned_input(path)
            for path in helper_owned_input_paths
        )
        return tuple(sorted(set(authorized)))

    def checkpoint_scope(self) -> CheckpointScope:
        return CheckpointScope(
            repo_root=self.repo_root,
            protected_patterns=self.config.protected_paths,
            report_patterns=self.config.adapter_report_paths,
        )

    def _require_inside_repository(self, normalized: str) -> None:
        try:
            (self.repo_root / normalized).resolve(strict=False).relative_to(
                self.repo_root
            )
        except (OSError, RuntimeError, ValueError) as error:
            raise _not_authorized("path escapes repository") from error

    def _require_not_denied(self, normalized: str) -> None:
        patterns = _INTERNAL_DENY_PATTERNS + self.config.protected_paths
        if _matches_any_path_or_ancestor(normalized, patterns):
            raise _not_authorized("path is protected")

    def _require_allowed_for_kind(
        self,
        kind: PathKind,
        normalized: str,
        *,
        helper_owned_report_paths: tuple[str, ...],
    ) -> None:
        if kind == "input":
            allow_patterns = (
                self.config.adapter_source_paths + self.config.adapter_test_paths
            )
            if allow_patterns:
                if not _matches_any_path_or_ancestor(normalized, allow_patterns):
                    raise _not_authorized("input path is not allowed by adapter")
                return
            fallback = self._configured_or_fallback_input_candidates()
            if not _is_within_any_candidate(normalized, fallback):
                raise _not_authorized("input path is not allowed by fallback policy")
            return
        if kind == "generated-test":
            if not _matches_any_path_or_ancestor(
                normalized,
                self.config.adapter_generated_test_destinations,
            ):
                raise _not_authorized(
                    "generated test path is not allowed by adapter"
                )
            return
        if kind == "report":
            helper_paths = tuple(_normalize(path) for path in helper_owned_report_paths)
            if normalized in helper_paths:
                return
            if not _matches_any_path_or_ancestor(
                normalized,
                self.config.adapter_report_paths,
            ):
                raise _not_authorized("report path is not allowed by adapter")
            return
        raise _not_authorized(f"unsupported path kind: {kind}")

    def _configured_or_fallback_input_candidates(self) -> tuple[str, ...]:
        patterns = self.config.adapter_source_paths + self.config.adapter_test_paths
        if patterns:
            roots = [_pattern_root(pattern) for pattern in patterns]
            return tuple(
                sorted(
                    set(
                        candidate
                        for root in roots
                        for candidate in self._safe_input_roots(root)
                    )
                )
            )

        candidates: list[str] = []
        fallback_denies = self._fallback_input_denies()
        for entry in sorted(self.repo_root.iterdir(), key=lambda item: item.name):
            try:
                relative = entry.relative_to(self.repo_root).as_posix()
            except ValueError:
                continue
            if entry.is_symlink():
                continue
            candidates.extend(
                self._safe_input_roots(
                    relative,
                    extra_denied_patterns=fallback_denies,
                )
            )
        return tuple(sorted(set(candidates)))

    def _fallback_input_denies(self) -> tuple[str, ...]:
        wiki_patterns: tuple[str, ...] = ()
        try:
            wiki = self.config.wiki_path.resolve(strict=False).relative_to(
                self.repo_root
            )
        except ValueError:
            wiki = None
        if wiki is not None and wiki.as_posix() not in ("", "."):
            wiki_path = wiki.as_posix()
            wiki_patterns = (wiki_path, f"{wiki_path}/**")
        return _FALLBACK_INPUT_DENY_PATTERNS + wiki_patterns

    def _safe_input_roots(
        self,
        root: str,
        *,
        extra_denied_patterns: tuple[str, ...] = (),
    ) -> tuple[str, ...]:
        normalized = _normalize(root)
        denied_patterns = (
            _INTERNAL_DENY_PATTERNS
            + self.config.protected_paths
            + extra_denied_patterns
        )
        if _matches_any_path_or_ancestor(normalized, denied_patterns):
            return ()
        path = self.repo_root / normalized
        try:
            path.resolve(strict=False).relative_to(self.repo_root)
        except (OSError, RuntimeError, ValueError):
            return ()
        if not path.exists():
            return (normalized,)
        if path.is_symlink():
            return ()
        if path.is_file():
            return (normalized,)
        if not path.is_dir():
            return ()
        children = [
            child.relative_to(self.repo_root).as_posix()
            for child in sorted(path.iterdir(), key=lambda item: item.name)
        ]
        denied_children = [
            child
            for child in children
            if self._input_candidate_needs_descent(
                child,
                denied_patterns=denied_patterns,
            )
        ]
        if not denied_children:
            return (normalized,)
        safe: list[str] = []
        for child in children:
            safe.extend(
                self._safe_input_roots(
                    child,
                    extra_denied_patterns=extra_denied_patterns,
                )
            )
        return tuple(safe)

    def _input_candidate_needs_descent(
        self,
        normalized: str,
        *,
        denied_patterns: tuple[str, ...],
    ) -> bool:
        if _matches_any_path_or_ancestor(normalized, denied_patterns):
            return True
        path = self.repo_root / normalized
        try:
            path.resolve(strict=False).relative_to(self.repo_root)
        except (OSError, RuntimeError, ValueError):
            return True
        if path.is_symlink() or not path.is_dir():
            return False
        return any(
            self._input_candidate_needs_descent(
                child.relative_to(self.repo_root).as_posix(),
                denied_patterns=denied_patterns,
            )
            for child in path.iterdir()
        )

    def _authorize_helper_owned_input(self, path: str) -> str:
        normalized = _normalize(path)
        self._require_inside_repository(normalized)
        self._require_not_denied(normalized)
        return normalized


def _authorize_checkpoint_candidate(
    repo_root: Path,
    path: str,
    *,
    protected_patterns: tuple[str, ...],
    report_patterns: tuple[str, ...],
) -> str:
    repository = repo_root.resolve(strict=True)
    normalized = _normalize(path)
    patterns = _INTERNAL_DENY_PATTERNS + protected_patterns + report_patterns
    if _matches_any_path_or_ancestor(normalized, patterns):
        raise _not_authorized("checkpoint path is protected")
    candidate = repository / normalized
    try:
        candidate.resolve(strict=False).relative_to(repository)
    except (OSError, RuntimeError, ValueError) as error:
        raise _not_authorized("checkpoint path escapes repository") from error
    try:
        metadata = candidate.lstat()
    except OSError as error:
        raise _not_authorized("checkpoint path does not exist") from error
    mode = metadata.st_mode
    if stat.S_ISLNK(mode):
        raise _not_authorized("checkpoint path must not be a symlink")
    if stat.S_ISDIR(mode):
        if (candidate / ".git").exists():
            raise _not_authorized("checkpoint path must not be a gitlink")
        for descendant in candidate.rglob("*"):
            try:
                descendant_relative = descendant.relative_to(repository).as_posix()
            except ValueError as error:
                raise _not_authorized(
                    "checkpoint path escapes repository"
                ) from error
            if _matches_any_path_or_ancestor(descendant_relative, patterns):
                raise _not_authorized(
                    "checkpoint directory contains a protected path"
                )
            if descendant.is_symlink():
                raise _not_authorized(
                    "checkpoint directory contains a symlink"
                )
            descendant_mode = descendant.lstat().st_mode
            if not (stat.S_ISDIR(descendant_mode) or stat.S_ISREG(descendant_mode)):
                raise _not_authorized(
                    "checkpoint directory contains a special file"
                )
        return normalized
    if stat.S_ISREG(mode):
        return normalized
    raise _not_authorized("checkpoint path must be a regular file or directory")


def _normalize(path: str) -> str:
    if not isinstance(path, str) or not path.strip() or "\\" in path:
        raise _not_authorized("path must be a repository-relative POSIX path")
    pure = PurePosixPath(path)
    if (
        pure.is_absolute()
        or pure.as_posix() != path
        or pure.as_posix() == "."
        or ".." in pure.parts
    ):
        raise _not_authorized("path must be normalized repository-relative POSIX")
    return pure.as_posix()


def _pattern_root(pattern: str) -> str:
    _validate_pattern(pattern)
    parts = PurePosixPath(pattern).parts
    root: list[str] = []
    for part in parts:
        if any(character in part for character in "*?["):
            break
        root.append(part)
    if not root:
        raise _not_authorized("adapter path pattern must have a literal root")
    return PurePosixPath(*root).as_posix()


def _validate_pattern(pattern: str) -> None:
    if not isinstance(pattern, str) or not pattern.strip() or "\\" in pattern:
        raise _not_authorized("configured path pattern is invalid")
    pure = PurePosixPath(pattern)
    if (
        pure.is_absolute()
        or pure.as_posix() != pattern
        or pure.as_posix() == "."
        or ".." in pure.parts
    ):
        raise _not_authorized("configured path pattern is invalid")


def _matches_any_path_or_ancestor(path: str, patterns: tuple[str, ...]) -> bool:
    return any(
        _matches_path_or_ancestor(path, pattern)
        for pattern in patterns
    )


def _matches_path_or_ancestor(path: str, pattern: str) -> bool:
    _validate_pattern(pattern)
    for candidate in _path_and_ancestors(path):
        if _matches_pattern(candidate, pattern):
            return True
    return False


def _path_and_ancestors(path: str) -> tuple[str, ...]:
    parts = PurePosixPath(path).parts
    return tuple(
        PurePosixPath(*parts[:index]).as_posix()
        for index in range(len(parts), 0, -1)
    )


def _matches_pattern(path: str, pattern: str) -> bool:
    if fnmatchcase(path, pattern):
        return True
    if pattern.endswith("/**") and path == pattern[:-3]:
        return True
    return False


def _is_within_any_candidate(path: str, candidates: tuple[str, ...]) -> bool:
    return any(path == candidate or path.startswith(f"{candidate}/") for candidate in candidates)


def _not_authorized(message: str) -> AppError:
    return AppError("path_not_authorized", message)
