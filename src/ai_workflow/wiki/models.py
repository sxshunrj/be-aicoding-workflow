from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
import json
import re
from pathlib import Path
from typing import Mapping

from ai_workflow.errors import AppError


ID_PATTERN = re.compile(r"KW-[a-z0-9-]+-[0-9]{3,}")
PROPOSAL_RAW_LOG_LIMIT = 64_000
PROPOSAL_CONFIDENCE = {"low", "medium", "high"}


class KnowledgeStatus(StrEnum):
    CANDIDATE = "candidate"
    APPROVED = "approved"
    ARCHIVED = "archived"
    SUPERSEDED = "superseded"


class KnowledgeType(StrEnum):
    RULE = "rule"
    DECISION = "decision"
    PATTERN = "pattern"
    PITFALL = "pitfall"
    PROCEDURE = "procedure"
    DIAGNOSTIC = "diagnostic"
    WORKFLOW = "workflow"


@dataclass(frozen=True, slots=True)
class KnowledgeScope:
    repos: tuple[str, ...] = ()
    services: tuple[str, ...] = ()
    paths: tuple[str, ...] = ()
    languages: tuple[str, ...] = ()
    phases: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class KnowledgeEntry:
    id: str
    title: str
    type: KnowledgeType
    status: KnowledgeStatus
    summary: str
    scope: KnowledgeScope
    tags: tuple[str, ...]
    owners: tuple[str, ...]
    reviewers: tuple[str, ...]
    created_at: date
    reviewed_at: date | None
    review_after: date
    sources: tuple[dict[str, str], ...]
    supersedes: tuple[str, ...]
    conflicts_with: tuple[str, ...]
    body: str

    @classmethod
    def from_parts(
        cls,
        metadata: Mapping[str, object],
        body: str,
        *,
        allowed_types: set[str] | None = None,
        allowed_phases: set[str] | None = None,
    ) -> "KnowledgeEntry":
        def text(name: str) -> str:
            value = metadata.get(name)
            if not isinstance(value, str) or not value.strip():
                raise AppError("wiki_invalid", f"{name} must not be empty")
            return value.strip()

        def strings(value: object, name: str, required: bool = False) -> tuple[str, ...]:
            if not isinstance(value, list) or not all(
                isinstance(item, str) and item.strip() for item in value
            ):
                raise AppError("wiki_invalid", f"{name} must be a list of non-empty strings")
            result = tuple(item.strip() for item in value)
            if required and not result:
                raise AppError("wiki_invalid", f"{name} must not be empty")
            return result

        entry_id = text("id")
        validate_entry_id(entry_id)
        try:
            kind = KnowledgeType(text("type"))
            status = KnowledgeStatus(text("status"))
        except ValueError as error:
            raise AppError("wiki_invalid", "unknown knowledge type or status") from error
        if allowed_types is not None and kind.value not in allowed_types:
            raise AppError("wiki_invalid", f"type is not allowed by taxonomy: {kind.value}")
        raw_scope = metadata.get("scope")
        if not isinstance(raw_scope, dict):
            raise AppError("wiki_invalid", "scope must be a mapping")
        scope = KnowledgeScope(**{
            name: strings(raw_scope.get(name, []), f"scope.{name}")
            for name in ("repos", "services", "paths", "languages", "phases")
        })
        phases = allowed_phases or {"spec", "plan", "implement", "verify"}
        unknown = set(scope.phases) - phases
        if unknown:
            raise AppError("wiki_invalid", f"phase is not allowed by taxonomy: {sorted(unknown)[0]}")
        created_at = _date(metadata.get("created_at"), "created_at")
        reviewed_at = _date(metadata.get("reviewed_at"), "reviewed_at", optional=True)
        review_after = _date(metadata.get("review_after"), "review_after")
        assert created_at is not None and review_after is not None
        if reviewed_at is not None and review_after < reviewed_at:
            raise AppError("wiki_invalid", "review_after must not precede reviewed_at")
        reviewers = strings(metadata.get("reviewers"), "reviewers")
        if status is KnowledgeStatus.APPROVED and not reviewers:
            raise AppError("wiki_invalid", "approved knowledge requires a reviewer")
        if status is KnowledgeStatus.APPROVED and reviewed_at is None:
            raise AppError("wiki_invalid", "approved knowledge requires reviewed_at")
        raw_sources = metadata.get("sources")
        if not isinstance(raw_sources, list):
            raise AppError("wiki_invalid", "sources must be a list")
        sources: list[dict[str, str]] = []
        for source in raw_sources:
            if not isinstance(source, dict) or source.get("kind") not in {"run", "human"}:
                raise AppError("wiki_invalid", "source must have a run or human kind and ref")
            reference = source.get("ref")
            if not isinstance(reference, str) or not reference.strip():
                raise AppError("wiki_invalid", "source must have a run or human kind and ref")
            sources.append({"kind": str(source["kind"]), "ref": reference.strip()})
        if not sources:
            message = "candidate knowledge requires a source" if status is KnowledgeStatus.CANDIDATE else "sources must not be empty"
            raise AppError("wiki_invalid", message)
        if not body.strip():
            raise AppError("wiki_invalid", "Markdown body must not be empty")
        return cls(
            entry_id, text("title"), kind, status, text("summary"), scope,
            strings(metadata.get("tags"), "tags"), strings(metadata.get("owners"), "owners", True),
            reviewers, created_at, reviewed_at, review_after, tuple(sources),
            strings(metadata.get("supersedes"), "supersedes"),
            strings(metadata.get("conflicts_with"), "conflicts_with"), body.strip(),
        )


@dataclass(frozen=True, slots=True)
class CandidateProposal:
    title: str
    type: KnowledgeType
    summary: str
    body: str
    scope: KnowledgeScope
    tags: tuple[str, ...]
    sources: tuple[dict[str, str], ...]
    reuse_reason: str
    confidence: str
    possible_conflicts: tuple[str, ...]
    suggested_owners: tuple[str, ...]
    review_after: date
    raw_logs: str = ""

    @classmethod
    def from_json(cls, path: Path) -> "CandidateProposal":
        try:
            loaded = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise AppError("wiki_invalid", f"proposal JSON is invalid: {error}") from error
        if not isinstance(loaded, dict):
            raise AppError("wiki_invalid", "proposal JSON must be a mapping")
        required = {
            "schema_version", "title", "type", "summary", "body", "scope", "tags",
            "sources", "reuse_reason", "confidence", "possible_conflicts",
            "suggested_owners", "review_after",
        }
        missing = sorted(required - set(loaded))
        if missing:
            raise AppError("wiki_invalid", f"proposal JSON is missing required field: {missing[0]}")
        if loaded.get("schema_version") != 1:
            raise AppError("wiki_invalid", "proposal JSON must be a schema_version 1 mapping")
        title = _proposal_text(loaded, "title")
        summary = _proposal_text(loaded, "summary")
        body = _proposal_text(loaded, "body")
        reuse_reason = _proposal_text(loaded, "reuse_reason")
        confidence = _proposal_text(loaded, "confidence").casefold()
        if confidence not in PROPOSAL_CONFIDENCE:
            raise AppError("wiki_invalid", "confidence must be one of: low, medium, high")
        raw_logs = loaded.get("raw_logs", "")
        if raw_logs is None:
            raw_logs = ""
        if not isinstance(raw_logs, str):
            raise AppError("wiki_invalid", "raw logs must be a string")
        if len(raw_logs) > PROPOSAL_RAW_LOG_LIMIT:
            raise AppError("wiki_invalid", "raw logs exceed the configured size")
        raw_scope = loaded.get("scope")
        if not isinstance(raw_scope, dict):
            raise AppError("wiki_invalid", "scope must be a mapping")
        scope = KnowledgeScope(**{
            name: _proposal_strings(raw_scope.get(name, []), f"scope.{name}")
            for name in ("repos", "services", "paths", "languages", "phases")
        })
        tags = _proposal_strings(loaded.get("tags"), "tags")
        sources = _proposal_sources(loaded.get("sources"))
        if not sources:
            raise AppError("wiki_invalid", "candidate proposal evidence must not be empty")
        possible_conflicts = _proposal_strings(loaded.get("possible_conflicts"), "possible_conflicts")
        suggested_owners = _proposal_strings(loaded.get("suggested_owners"), "suggested_owners", required=True)
        review_after = _date(loaded.get("review_after"), "review_after")
        assert review_after is not None
        try:
            kind = KnowledgeType(_proposal_text(loaded, "type"))
        except ValueError as error:
            raise AppError("wiki_invalid", "unknown knowledge type") from error
        return cls(
            title=title,
            type=kind,
            summary=summary,
            body=body,
            scope=scope,
            tags=tags,
            sources=tuple(sources),
            reuse_reason=reuse_reason,
            confidence=confidence,
            possible_conflicts=possible_conflicts,
            suggested_owners=suggested_owners,
            review_after=review_after,
            raw_logs=raw_logs,
        )

    def to_entry(self, entry_id: str, created_at: date) -> KnowledgeEntry:
        return KnowledgeEntry(
            entry_id,
            self.title,
            self.type,
            KnowledgeStatus.CANDIDATE,
            self.summary,
            self.scope,
            self.tags,
            self.suggested_owners,
            (),
            created_at,
            None,
            self.review_after,
            self.sources,
            (),
            self.possible_conflicts,
            self.body,
        )


def validate_entry_id(entry_id: object) -> str:
    if not isinstance(entry_id, str) or ID_PATTERN.fullmatch(entry_id) is None:
        raise AppError("wiki_invalid", "knowledge id is invalid")
    return entry_id


def _date(value: object, name: str, optional: bool = False) -> date | None:
    if value is None and optional:
        return None
    if type(value) is date:
        return value
    if isinstance(value, datetime):
        raise AppError("wiki_invalid", f"{name} must be an ISO date")
    if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    raise AppError("wiki_invalid", f"{name} must be an ISO date")


def _proposal_text(metadata: Mapping[str, object], name: str) -> str:
    value = metadata.get(name)
    if not isinstance(value, str) or not value.strip():
        raise AppError("wiki_invalid", f"{name} must not be empty")
    return value.strip()


def _proposal_strings(value: object, name: str, *, required: bool = False) -> tuple[str, ...]:
    if value is None and not required:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise AppError("wiki_invalid", f"{name} must be a list of non-empty strings")
    result = tuple(item.strip() for item in value)
    if required and not result:
        raise AppError("wiki_invalid", f"{name} must not be empty")
    return result


def _proposal_sources(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise AppError("wiki_invalid", "sources must be a list")
    sources: list[dict[str, str]] = []
    for source in value:
        if not isinstance(source, dict) or source.get("kind") not in {"run", "human"}:
            raise AppError("wiki_invalid", "source must have a run or human kind and ref")
        reference = source.get("ref")
        if not isinstance(reference, str) or not reference.strip():
            raise AppError("wiki_invalid", "source must have a run or human kind and ref")
        sources.append({"kind": str(source["kind"]), "ref": reference.strip()})
    return sources
