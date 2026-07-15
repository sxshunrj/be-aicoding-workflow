from dataclasses import dataclass
from datetime import date
import hashlib
import json
from pathlib import Path

from ai_workflow.errors import AppError
from ai_workflow.wiki.repository import DIRECTORY, WikiRepository
from ai_workflow.contracts.artifacts import SCHEMA_VERSION
from ai_workflow.contracts.packets import KnowledgePacket
from ai_workflow.wiki.search import KnowledgeQuery, KnowledgeSearcher, SearchLimits


@dataclass(frozen=True, slots=True)
class LintReport:
    valid: bool
    issues: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {"valid": self.valid, "issues": list(self.issues)}


class WikiService:
    def __init__(self, repository: WikiRepository, *, today=date.today) -> None:
        self.repository = repository
        self.today = today

    def search(self, query: KnowledgeQuery, limits: SearchLimits) -> tuple:
        entries = [self.repository.read(path) for path in self.repository.paths()]
        return KnowledgeSearcher(entries, today=self.today).search(query, limits)

    def create_packet(self, query: KnowledgeQuery, output_path: Path,
                      limits: SearchLimits = SearchLimits()) -> KnowledgePacket:
        selected: list[dict[str, object]] = []
        selected_ids: list[str] = []
        for result in self.search(query, limits):
            entry = result.entry
            item = {"id": entry.id, "title": entry.title, "type": entry.type.value,
                    "summary": entry.summary, "content": entry.body,
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
