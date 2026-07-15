from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date

from ai_workflow.wiki.models import KnowledgeEntry, KnowledgeStatus


@dataclass(frozen=True, slots=True)
class KnowledgeQuery:
    repository: str | None = None
    services: tuple[str, ...] = ()
    paths: tuple[str, ...] = ()
    languages: tuple[str, ...] = ()
    phase: str | None = None
    types: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    text: str = ""

    def to_dict(self) -> dict[str, object]:
        return {"repository": self.repository, "services": list(self.services),
                "paths": list(self.paths), "languages": list(self.languages),
                "phase": self.phase, "types": list(self.types),
                "tags": list(self.tags), "text": self.text}


@dataclass(frozen=True, slots=True)
class SearchLimits:
    max_entries: int = 8
    max_characters: int = 12000

    def __post_init__(self) -> None:
        if self.max_entries < 0 or self.max_characters < 0:
            raise ValueError("search limits must not be negative")


@dataclass(frozen=True, slots=True)
class SearchResult:
    entry: KnowledgeEntry
    score: int
    match_reasons: tuple[str, ...]
    warnings: tuple[str, ...]


def _tokens(value: str) -> set[str]:
    return set(value.casefold().split())


class KnowledgeSearcher:
    def __init__(self, entries: Iterable[KnowledgeEntry], *,
                 today: Callable[[], date] = date.today) -> None:
        self.entries = tuple(entries)
        self.today = today

    def search(self, query: KnowledgeQuery, limits: SearchLimits) -> tuple[SearchResult, ...]:
        query_tokens = _tokens(query.text)
        query_has_constraints = bool(
            query.text or query.tags or query.repository or query.services or query.paths
            or query.languages or query.phase or query.types
        )
        results: list[SearchResult] = []
        for entry in self.entries:
            if entry.status is not KnowledgeStatus.APPROVED:
                continue
            if query.types and entry.type.value not in query.types:
                continue
            score, reasons, matched = self._score(entry, query, query_tokens)
            if query_has_constraints and not matched:
                continue
            warnings = []
            if entry.review_after < self.today():
                warnings.append(f"review overdue since {entry.review_after.isoformat()}")
            warnings.extend(f"conflicts with {item}" for item in entry.conflicts_with)
            results.append(SearchResult(entry, score, tuple(reasons), tuple(warnings)))
        results.sort(key=lambda item: (-item.score, item.entry.id))
        return tuple(results[:limits.max_entries])

    @staticmethod
    def _score(entry: KnowledgeEntry, query: KnowledgeQuery,
               query_tokens: set[str]) -> tuple[int, list[str], bool]:
        score = 0
        reasons: list[str] = []
        matched = False
        checks = ((query.repository, entry.scope.repos, "repository"),
                  (query.services, entry.scope.services, "service"),
                  (query.paths, entry.scope.paths, "path"),
                  (query.languages, entry.scope.languages, "language"),
                  (query.phase, entry.scope.phases, "phase"))
        for wanted, available, label in checks:
            values = (wanted,) if isinstance(wanted, str) else wanted
            for value in values or ():
                if value and value.casefold() in {item.casefold() for item in available}:
                    score += 40
                    reasons.append(f"{label}:{value}")
                    matched = True
        for tag in query.tags:
            if tag.casefold() in {item.casefold() for item in entry.tags}:
                score += 30
                reasons.append(f"tag:{tag}")
                matched = True
        title = query_tokens & _tokens(entry.title)
        summary = query_tokens & _tokens(entry.summary)
        body = query_tokens & _tokens(entry.body)
        for label, matches, points in (("title", title, 20), ("summary", summary, 10),
                                       ("body", body, 2)):
            score += points * len(matches)
            reasons.extend(f"{label}:{token}" for token in sorted(matches))
            matched = matched or bool(matches)
        scope = entry.scope
        if not (scope.repos or scope.services or scope.paths or scope.languages or scope.phases):
            score += 1
            reasons.append("broad-scope")
        return score, reasons, matched
