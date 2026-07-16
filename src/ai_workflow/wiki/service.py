from dataclasses import dataclass
from datetime import date
import hashlib
import json
from pathlib import Path
import re
from dataclasses import replace

from ai_workflow.errors import AppError
from ai_workflow.wiki.models import CandidateProposal, KnowledgeEntry, KnowledgeStatus, KnowledgeType
from ai_workflow.wiki.repository import DIRECTORY, WikiRepository
from ai_workflow.contracts.artifacts import SCHEMA_VERSION
from ai_workflow.contracts.packets import KnowledgePacket
from ai_workflow.wiki.search import KnowledgeQuery, KnowledgeSearcher, SearchLimits


ID_SEQUENCE_PATTERN = re.compile(r"KW-[a-z0-9-]+-([0-9]{3,})$")


@dataclass(frozen=True, slots=True)
class LintReport:
    valid: bool
    issues: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {"valid": self.valid, "issues": list(self.issues)}


def _excerpt(text: str, query: str, limit: int = 240) -> str:
    normalized = " ".join(text.split()).strip()
    if not normalized:
        return ""
    tokens = [token for token in query.casefold().split() if token]
    lowered = normalized.casefold()
    start = 0
    for token in tokens:
        index = lowered.find(token)
        if index != -1:
            start = max(0, index - 60)
            break
    excerpt = normalized[start:start + limit]
    if start > 0:
        excerpt = f"...{excerpt}"
    if start + limit < len(normalized):
        excerpt = f"{excerpt.rstrip()}..."
    return excerpt


class WikiService:
    def __init__(self, repository: WikiRepository, *, today=date.today) -> None:
        self.repository = repository
        self.today = today

    def propose(self, proposal_path: Path) -> KnowledgeEntry:
        proposal = CandidateProposal.from_json(proposal_path)
        entry = proposal.to_entry(self._next_candidate_id(proposal.type, proposal.title), self.today())
        self.repository.write_candidate(entry)
        return entry

    def review_candidate(
        self, entry_id: str, max_related: int = 8
    ) -> dict[str, object]:
        if max_related < 0:
            raise AppError("wiki_invalid", "max_related must not be negative")
        candidates = [
            path
            for path in self.repository.paths()
            if path.name == f"{entry_id}.md"
            or self.repository.read(path).id == entry_id
        ]
        if len(candidates) != 1:
            raise AppError("wiki_not_found", f"candidate knowledge not found: {entry_id}")
        candidate_path = candidates[0]
        candidate = self.repository.read(candidate_path)
        if candidate.status is not KnowledgeStatus.CANDIDATE:
            raise AppError("wiki_invalid", "knowledge entry is not a candidate")
        query = KnowledgeQuery(
            repository=(candidate.scope.repos[0] if candidate.scope.repos else None),
            services=candidate.scope.services,
            paths=candidate.scope.paths,
            languages=candidate.scope.languages,
            phase=(candidate.scope.phases[0] if candidate.scope.phases else None),
            types=(candidate.type.value,),
            tags=candidate.tags,
            text=f"{candidate.title} {candidate.summary}",
        )
        related = []
        excluded = {candidate.id, *candidate.conflicts_with, *candidate.supersedes}
        for result in self.search(
            query,
            SearchLimits(max_entries=max_related + len(excluded), max_characters=12000),
        ):
            if result.entry.id in excluded:
                continue
            path = self.repository.root / "approved" / f"{result.entry.id}.md"
            related.append(
                {
                    "id": result.entry.id,
                    "title": result.entry.title,
                    "score": result.score,
                    "digest": self.repository.path_digest(path),
                    "match_reasons": list(result.match_reasons),
                }
            )
            if len(related) >= max_related:
                break
        return {
            "candidate": {
                "id": candidate.id,
                "title": candidate.title,
                "type": candidate.type.value,
                "digest": self.repository.path_digest(candidate_path),
                "status": candidate.status.value,
            },
            "related_approved": related,
            "declared_conflicts": list(candidate.conflicts_with),
            "declared_supersedes": list(candidate.supersedes),
        }

    def promote(self, entry_id: str, reviewer: str, expected_digest: str) -> KnowledgeEntry:
        candidate_path = self.repository.root / "candidates" / f"{entry_id}.md"
        self._guard_digest(candidate_path, expected_digest, "candidate changed since review")
        entry = self.repository.read(candidate_path)
        if entry.status is not KnowledgeStatus.CANDIDATE:
            raise AppError("wiki_invalid", "candidate entry is not a candidate")
        self._validate_references(entry)
        approved = replace(
            entry,
            status=KnowledgeStatus.APPROVED,
            reviewers=self._append_unique(entry.reviewers, reviewer),
            reviewed_at=self.today(),
        )
        self.repository.replace_and_move(
            approved,
            KnowledgeStatus.CANDIDATE,
            KnowledgeStatus.APPROVED,
            expected_digest=expected_digest,
        )
        return approved

    def reject(self, entry_id: str, reviewer: str, reason: str, expected_digest: str) -> Path:
        candidate_path = self.repository.root / "candidates" / f"{entry_id}.md"
        self._guard_digest(candidate_path, expected_digest, "candidate changed since review")
        entry = self.repository.read(candidate_path)
        if entry.status is not KnowledgeStatus.CANDIDATE:
            raise AppError("wiki_invalid", "candidate entry is not a candidate")
        archived = self._archive_entry(entry, reviewer, reason)
        return self.repository.replace_and_move(
            archived,
            KnowledgeStatus.CANDIDATE,
            KnowledgeStatus.ARCHIVED,
            expected_digest=expected_digest,
        )

    def archive(self, entry_id: str, reviewer: str, reason: str, expected_digest: str) -> Path:
        approved_path = self.repository.root / "approved" / f"{entry_id}.md"
        self._guard_digest(approved_path, expected_digest, "approved entry changed since review")
        entry = self.repository.read(approved_path)
        if entry.status is not KnowledgeStatus.APPROVED:
            raise AppError("wiki_invalid", "approved entry is not approved")
        archived = self._archive_entry(entry, reviewer, reason)
        return self.repository.replace_and_move(
            archived,
            KnowledgeStatus.APPROVED,
            KnowledgeStatus.ARCHIVED,
            expected_digest=expected_digest,
        )

    def search(self, query: KnowledgeQuery, limits: SearchLimits) -> tuple:
        entries = [self.repository.read(path) for path in self.repository.paths()]
        return KnowledgeSearcher(entries, today=self.today).search(query, limits)

    def create_packet(self, query: KnowledgeQuery, output_path: Path,
                      limits: SearchLimits = SearchLimits()) -> KnowledgePacket:
        selected: list[dict[str, object]] = []
        selected_ids: list[str] = []
        for result in self.search(query, limits):
            entry = result.entry
            content_source = f"{entry.summary} {entry.body}".strip()
            item = {"id": entry.id, "title": entry.title, "type": entry.type.value,
                    "summary": entry.summary, "content": _excerpt(content_source, query.text),
                    "match_reasons": list(result.match_reasons),
                    "warnings": list(result.warnings),
                    "paths": list(entry.scope.paths)}
            candidate_entries = (*selected, item)
            unsigned = {"schema_version": SCHEMA_VERSION, "query": query.to_dict(),
                        "selected_ids": [*selected_ids, entry.id],
                        "entries": list(candidate_entries)}
            digest = hashlib.sha256(json.dumps(unsigned, sort_keys=True,
                                                separators=(",", ":")).encode()).hexdigest()
            complete = {**unsigned, "digest": digest}
            if len(json.dumps(complete, indent=2) + "\n") > limits.max_characters:
                break
            selected.append(item)
            selected_ids.append(entry.id)
        unsigned = {"schema_version": SCHEMA_VERSION, "query": query.to_dict(),
                    "selected_ids": selected_ids, "entries": selected}
        digest = hashlib.sha256(json.dumps(unsigned, sort_keys=True,
                                            separators=(",", ":")).encode()).hexdigest()
        packet = KnowledgePacket(query.to_dict(), tuple(selected_ids), tuple(selected), digest)
        serialized = json.dumps(packet.to_dict(), indent=2) + "\n"
        if len(serialized) > limits.max_characters:
            raise AppError("knowledge_limit", "knowledge packet metadata exceeds character limit")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(serialized, encoding="utf-8")
        return packet

    def lint(self) -> LintReport:
        issues: list[str] = []
        entries = []
        try:
            self.repository.taxonomy()
            paths, enumeration_issues = self.repository.raw_paths()
            issues.extend(enumeration_issues)
        except AppError as error:
            return LintReport(False, (f"taxonomy/layout: {error.message}",))
        for path in paths:
            try:
                entry = self.repository.read(path)
            except AppError as error:
                issues.append(f"{path.relative_to(self.repository.root)}: {error.message}")
                continue
            entries.append((path, entry))
            if path.parent.name != DIRECTORY[entry.status]:
                issues.append(
                    f"{path.relative_to(self.repository.root)}: directory does not match status {entry.status.value}"
                )
        counts: dict[str, int] = {}
        for _, entry in entries:
            counts[entry.id] = counts.get(entry.id, 0) + 1
        for path, entry in entries:
            relative = path.relative_to(self.repository.root)
            if counts[entry.id] > 1:
                issues.append(f"{relative}: duplicate knowledge id {entry.id}")
            for relation, references in (
                ("supersedes", entry.supersedes),
                ("conflicts_with", entry.conflicts_with),
            ):
                for reference in references:
                    if reference == entry.id:
                        issues.append(f"{relative}: {relation} must not reference itself: {reference}")
                    elif reference not in counts:
                        issues.append(f"{relative}: referenced knowledge id does not exist: {reference}")
        ordered = tuple(sorted(set(issues)))
        return LintReport(not ordered, ordered)

    def _guard_digest(self, path: Path, expected_digest: str, message: str) -> None:
        actual = self.repository.file_digest(path)
        if actual != expected_digest:
            raise AppError("wiki_conflict", message)

    def _archive_entry(self, entry: KnowledgeEntry, reviewer: str, reason: str) -> KnowledgeEntry:
        note = "\n".join((
            "## Lifecycle note",
            f"- reviewer: {reviewer}",
            f"- reason: {reason}",
        ))
        reviewers = self._append_unique(entry.reviewers, reviewer)
        body = f"{entry.body.rstrip()}\n\n{note}\n"
        return replace(
            entry,
            status=KnowledgeStatus.ARCHIVED,
            reviewers=reviewers,
            reviewed_at=self.today(),
            body=body,
        )

    def _validate_references(self, entry: KnowledgeEntry) -> None:
        known_ids = {item.id for item in (self.repository.read(path) for path in self.repository.paths())}
        for relation, references in (("supersedes", entry.supersedes), ("conflicts_with", entry.conflicts_with)):
            for reference in references:
                if reference == entry.id:
                    raise AppError("wiki_invalid", f"{relation} must not reference itself: {reference}")
                if reference not in known_ids:
                    raise AppError("wiki_invalid", f"referenced knowledge id does not exist: {reference}")

    def _append_unique(self, values: tuple[str, ...], item: str) -> tuple[str, ...]:
        cleaned = item.strip()
        if not cleaned:
            raise AppError("wiki_invalid", "reviewer must not be empty")
        if cleaned in values:
            return values
        return (*values, cleaned)

    def _next_candidate_id(self, kind: KnowledgeType, title: str) -> str:
        highest = 0
        for path in self.repository.paths():
            match = ID_SEQUENCE_PATTERN.fullmatch(self.repository.read(path).id)
            if match is not None:
                highest = max(highest, int(match.group(1)))
        slug = _slugify(title)
        return f"KW-{kind.value}-{slug}-{highest + 1:03d}"


def _slugify(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return normalized or "entry"
